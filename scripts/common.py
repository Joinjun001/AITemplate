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
    "COOLDOWN_MIN_GEMINI": 60,   # Gemini(agy) 일일 한도 감지 시 기본 대기(분)
    "CYCLE_INTERVAL_MIN": 5,     # 스케줄러가 orchestrator를 부르는 주기(분)
    # 작업 브랜치를 만들 때 기준으로 삼고, 승인된 작업을 병합해 넣을 브랜치.
    # 실제 프로젝트는 "main"을 그대로 쓰면 되고, 템플릿 자체를 건드리지 않고
    # 연습/테스트를 해보고 싶으면 예: "practice/todo-api" 같은 별도 브랜치로
    # 바꿔서 그 브랜치 안에서만 orchestrator가 작업하게 격리할 수 있다.
    "BASE_BRANCH": "main",
    # run_project.py가 "할 일이 없다(쿨다운 중)"일 때 다음 시도까지 최소로
    # 재우는 시간(초). 실제로는 쿨다운이 끝나는 시각까지 알아서 더 길게 잔다.
    "RUN_LOOP_POLL_SEC": 20,
    # claude/Gemini CLI의 실행 파일 이름 또는 절대경로. 기본값은 그냥 이름이라
    # PATH에서 찾지만, install.py를 실행하면 그 시점에 실제로 resolve된
    # 절대경로로 자동으로 덮어써진다 — Windows 작업 스케줄러처럼 대화형 셸과
    # PATH가 다른 환경에서 "명령어를 찾을 수 없음"으로 실패하는 걸 원천적으로
    # 막기 위함이다(실제로 겪은 문제: 작업 스케줄러가 대화형 PowerShell과
    # 다른 PATH로 떠서 agy를 못 찾고 재시도만 깎아먹은 적이 있다).
    "CLAUDE_CLI_CMD": "claude",
    # Gemini 계정으로 로그인해서 쓰는 CLI의 실제 실행 파일 이름.
    # Antigravity CLI(agy)를 쓰면 "agy", 독립 Gemini CLI를 쓰면 "gemini"로 바꾸세요.
    "GEMINI_CLI_CMD": "agy",
    # agy는 --model 로 Gemini 외에 Claude 모델도 고를 수 있지만, 그건 Google
    # 플랜에 번들된 접근권이라 Anthropic Claude Pro 구독 한도와는 별개입니다.
    # 여기서는 항상 Gemini 계열 모델만 쓰도록 비워두고, 필요하면 예: "Gemini 3.1 Pro"
    "GEMINI_MODEL": "",
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


# claude CLI를 구독 로그인(claude login)이 아니라 API 키/커스텀 엔드포인트로
# 우회시키는 환경변수. 하나라도 설정돼 있으면 claude CLI가 Claude Pro/Max
# 구독 세션을 아예 안 쓰고, 이 값이 가리키는 곳(공식 Anthropic API 종량제거나
# 심지어 z.ai 같은 제3자 프록시)으로 요청을 보낸다. 무인 자동화 중에 이게
# 모르는 새 켜져 있으면 예상 못 한 과금이나 "잔액 부족" 에러로 이어질 수 있어서
# (실제로 겪은 사례: 예전에 연결해뒀던 z.ai용 ANTHROPIC_BASE_URL이 남아있어서
# orchestrator가 Claude Pro 구독 대신 z.ai 유료 잔액을 쓰다가 잔액 소진으로
# 막힌 적이 있다) 시작할 때마다 경고해준다.
DANGEROUS_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")


def warn_dangerous_env() -> list[str]:
    """위 환경변수 중 설정된 게 있으면 경고 로그를 남기고 이름 목록을 반환한다."""
    found = [name for name in DANGEROUS_ENV_VARS if os.environ.get(name)]
    if found:
        names = ", ".join(found)
        log(
            f"⚠️ 경고: {names} 환경변수가 설정되어 있습니다. claude CLI가 구독 로그인이 "
            "아니라 이 값으로 인증/우회되어, 의도하지 않은 과금이나 '잔액 부족(insufficient "
            "balance)' 오류가 날 수 있습니다. 구독 토큰만 쓰려면 이 환경변수를 지우고 "
            "(Windows PowerShell: [Environment]::SetEnvironmentVariable('이름', $null, "
            "'User') 후 터미널 재시작) 'claude login'으로 다시 로그인하세요."
        )
    return found


def warn_missing_clis() -> list[str]:
    """claude/Gemini CLI가 지금 이 프로세스의 PATH에서 실제로 찾아지는지
    확인하고, 못 찾으면 경고 로그를 남긴다(그리고 찾으면 어디서 찾았는지도
    로그에 남긴다 — 백그라운드 스케줄러와 대화형 셸이 서로 다른 PATH를 볼 때
    이 로그 한 줄이 원인 파악 시간을 크게 줄여준다). CLI가 없다고 여기서
    막지는 않는다 — 실제 실행 시점에 워커가 알아서 재시도 없이 todo로 남긴다."""
    missing = []
    for name, cmd in (
        ("claude", SETTINGS.get("CLAUDE_CLI_CMD", "claude")),
        ("gemini", SETTINGS.get("GEMINI_CLI_CMD", "agy")),
    ):
        resolved = shutil.which(cmd)
        if resolved:
            log(f"[환경확인] {name} CLI({cmd}) -> {resolved}")
        else:
            missing.append(cmd)
            log(
                f"⚠️ 경고: {name} CLI({cmd})를 이 프로세스의 PATH에서 찾을 수 없습니다. "
                f"PATH={os.environ.get('PATH', '')[:400]}"
            )
    return missing


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


def ensure_clean_repo(repo: Path) -> None:
    """이전 실행이 도중에 죽어서 merge/rebase가 진행 중인 상태로 남아있으면
    정리한다. 무인 자동화는 사람이 옆에서 'git merge --abort' 쳐줄 수 없으니,
    각 워커가 git 작업을 시작하기 전에 방어적으로 호출한다. 정리할 게 없으면
    조용히 아무 일도 안 한다."""
    if (repo / ".git" / "MERGE_HEAD").exists():
        log("이전 실행에서 남은 병합 충돌 상태 감지 -> git merge --abort로 정리")
        run_cli(["git", "merge", "--abort"], cwd=repo)


def claude_cli_argv(prompt: str, skip_permissions: bool = False) -> list[str]:
    """claude CLI 호출용 argv를 만든다. CLAUDE_CLI_CMD 설정으로 실행 파일
    이름/경로를 바꿀 수 있다(기본값 "claude", install.py가 절대경로로
    덮어쓸 수 있다)."""
    argv = [SETTINGS.get("CLAUDE_CLI_CMD", "claude"), "-p", prompt]
    if skip_permissions:
        argv.append("--dangerously-skip-permissions")
    return argv


def gemini_cli_argv(prompt: str, skip_permissions: bool = False) -> list[str]:
    """Gemini 계열(agy 또는 독립 gemini CLI) 호출용 argv를 만든다.

    GEMINI_CLI_CMD 설정으로 실제 명령어 이름을 바꿀 수 있다(기본값 "agy").
    agy는 -p/--dangerously-skip-permissions 등 Claude Code CLI와 거의 같은
    플래그 이름을 쓰므로 그대로 재사용한다.
    """
    argv = [SETTINGS.get("GEMINI_CLI_CMD", "agy"), "-p", prompt]
    model = SETTINGS.get("GEMINI_MODEL", "")
    if model:
        argv += ["--model", model]
    if skip_permissions:
        argv.append("--dangerously-skip-permissions")
    return argv


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


def seconds_until_cooldown_clears(name: str) -> float | None:
    """쿨다운 중이면 남은 초, 아니면 None. run_project.py가 '할 일이 아예
    없어서 쉬어야 하는' 동안 얼마나 오래 잘지 계산하는 데 쓴다."""
    path = _cooldown_path(name)
    if not path.exists():
        return None
    try:
        until_ts = float(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None
    remaining = until_ts - time.time()
    return remaining if remaining > 0 else None


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
