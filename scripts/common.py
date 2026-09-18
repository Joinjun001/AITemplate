#!/usr/bin/env python3
"""공통 설정과 헬퍼 함수. Linux/macOS/Windows에서 동일하게 동작하도록
bash+jq+flock 대신 표준 라이브러리만으로 구현했습니다."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = REPO_DIR / "state"
PROMPTS_DIR = REPO_DIR / "prompts"
TASKS_DIR = REPO_DIR / "tasks"
QUEUE_FILE = TASKS_DIR / "queue.jsonl"
LOG_FILE = STATE_DIR / "orchestrator.log"
LOCK_FILE = STATE_DIR / "orchestrator.lock"

STATE_DIR.mkdir(parents=True, exist_ok=True)
TASKS_DIR.mkdir(parents=True, exist_ok=True)
QUEUE_FILE.touch(exist_ok=True)

DEFAULTS = {
    "MAX_RETRIES": 3,
    "COOLDOWN_MIN_CLAUDE": 300,  # Claude 5시간 롤링 한도 감지 시 기본 대기(분)
    "COOLDOWN_MIN_GEMINI": 60,   # Gemini 일일 한도 감지 시 기본 대기(분)
    "CYCLE_INTERVAL_MIN": 5,     # 스케줄러가 orchestrator를 부르는 주기(분)
}


def load_settings() -> dict:
    settings = dict(DEFAULTS)
    cfg_file = REPO_DIR / "config" / "settings.json"
    if cfg_file.exists():
        try:
            settings.update(json.loads(cfg_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[경고] config/settings.json 파싱 실패, 기본값 사용: {e}", file=sys.stderr)
    return settings


SETTINGS = load_settings()


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def get_os() -> str:
    """'linux' | 'macos' | 'windows' | 'other' 중 하나."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    if system == "linux":
        return "linux"
    return "other"


def run_cli(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """claude/gemini/git 등을 실행하고 (returncode, stdout+stderr)를 반환.

    Windows에서 npm으로 설치된 CLI(claude.cmd, gemini.cmd 등)는 subprocess가
    shell=False일 때 PATHEXT를 자동으로 못 찾는 경우가 있어, shutil.which로
    미리 실제 경로를 찾아서 넘깁니다.
    """
    if not cmd:
        return 1, "빈 명령어"
    resolved = shutil.which(cmd[0])
    argv = [resolved, *cmd[1:]] if resolved else cmd
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError as e:
        return 127, f"명령어를 찾을 수 없음: {cmd[0]} ({e})"
    except OSError as e:
        return 126, f"명령어 실행 오류: {cmd[0]} ({e})"


# --- 파일 락: systemd/launchd/작업 스케줄러가 동시에 두 번 실행하는 걸 방지 ---
class AlreadyRunning(Exception):
    pass


def acquire_lock(stale_after_sec: int = 3600) -> None:
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age > stale_after_sec:
            log(f"오래된 락 파일 감지({age:.0f}초) -> 제거 후 진행")
            LOCK_FILE.unlink(missing_ok=True)
        else:
            raise AlreadyRunning(
                f"이미 실행 중인 orchestrator가 있어 이번 사이클은 건너뜀 (락 나이 {age:.0f}초)"
            )
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError as exc:
        raise AlreadyRunning("이미 실행 중인 orchestrator가 있어 이번 사이클은 건너뜀 (락 경합)") from exc


def release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


# --- 쿨다운(사용량 한도) 상태 ---
def _cooldown_path(name: str) -> Path:
    return STATE_DIR / f"{name}_until"


def is_cooling_down(name: str) -> bool:
    path = _cooldown_path(name)
    if not path.exists():
        return False
    try:
        until_ts = float(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        path.unlink(missing_ok=True)
        return False
    if until_ts > time.time():
        return True
    path.unlink(missing_ok=True)
    return False


LIMIT_PATTERN = re.compile(
    r"usage limit|rate limit|quota|resets? (at|in)|try again (later|in)|429",
    re.IGNORECASE,
)
TIME_PATTERN = re.compile(r"\b([0-9]{1,2}):([0-9]{2})\s*(AM|PM|am|pm)?\b")


def detect_limit_and_set_cooldown(output: str, name: str, default_minutes: int) -> bool:
    """CLI 출력에서 사용량 한도 메시지를 감지하면 쿨다운을 기록하고 True 반환.

    ⚠️ Claude Code / Gemini CLI 가 실제로 내보내는 리밋 메시지 문구는 버전에 따라
       달라질 수 있습니다. LIMIT_PATTERN이 실제 출력과 안 맞으면 이 정규식을
       고치세요 (state/orchestrator.log에 실제 출력 일부가 남습니다).
    """
    if not LIMIT_PATTERN.search(output):
        return False

    until_dt = None
    m = TIME_PATTERN.search(output)
    if m:
        hour, minute, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
        now = datetime.now()
        if ampm and ampm.lower() == "pm" and hour < 12:
            hour += 12
        candidate = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
        if candidate > now:
            until_dt = candidate

    if until_dt is None:
        until_dt = datetime.now() + timedelta(minutes=default_minutes)

    _cooldown_path(name).write_text(str(until_dt.timestamp()), encoding="utf-8")
    log(f"쿨다운 설정: {name} -> {until_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    return True
