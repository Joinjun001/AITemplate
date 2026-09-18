#!/usr/bin/env python3
"""OS를 자동 감지해서 그에 맞는 스케줄러에 orchestrator.py를 등록한다.

- Linux   -> systemd --user timer
- macOS   -> launchd (LaunchAgents plist)
- Windows -> 작업 스케줄러(schtasks)

사용법:
  python install.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = REPO_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import common  # noqa: E402

ORCH = SCRIPTS_DIR / "orchestrator.py"
PYTHON = sys.executable


def check_requirements() -> None:
    required = ["git", "claude", common.SETTINGS.get("GEMINI_CLI_CMD", "agy")]
    missing = [c for c in required if shutil.which(c) is None]
    if missing:
        print(f"[경고] PATH에서 다음 명령을 찾을 수 없습니다: {', '.join(missing)}")
        print("      설치 및 로그인(claude login / gemini 로그인) 후 다시 시도하세요.")
        print("      (일단 스케줄러 등록은 계속 진행합니다)\n")

    dangerous = common.warn_dangerous_env()
    if dangerous:
        print(
            f"[경고] {', '.join(dangerous)} 환경변수가 설정돼 있어서, claude CLI가 구독 로그인 "
            "대신 이 값으로 우회될 수 있습니다. 의도한 게 아니라면 지금 지우고 나서 설치를 "
            "계속하세요 (안 지우면 스케줄러가 무인으로 계속 그 값을 쓰게 됩니다).\n"
        )


def install_linux(interval_min: int) -> None:
    if shutil.which("systemctl") is None:
        print("systemctl을 찾을 수 없습니다.")
        print("WSL을 쓰고 있다면 /etc/wsl.conf 에 아래를 추가하고 'wsl --shutdown' 후 다시 시도하세요:")
        print("  [boot]")
        print("  systemd=true")
        sys.exit(1)

    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)

    service = f"""[Unit]
Description=AI Template orchestrator (Claude + Gemini task runner)

[Service]
Type=oneshot
WorkingDirectory={REPO_DIR}
ExecStart={PYTHON} {ORCH}
"""
    timer = f"""[Unit]
Description=Run AI Template orchestrator periodically

[Timer]
OnBootSec=2min
OnUnitActiveSec={interval_min}min
Persistent=true

[Install]
WantedBy=timers.target
"""
    (unit_dir / "ai-orchestrator.service").write_text(service, encoding="utf-8")
    (unit_dir / "ai-orchestrator.timer").write_text(timer, encoding="utf-8")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "ai-orchestrator.timer"], check=True)

    print("설치 완료 (systemd --user timer).")
    print("  상태 확인 : systemctl --user status ai-orchestrator.timer")
    print("  다음 실행 : systemctl --user list-timers ai-orchestrator.timer")
    print("  로그 확인 : journalctl --user -u ai-orchestrator.service -f")
    print("  로그아웃해도 계속 돌리려면: loginctl enable-linger $USER")


def install_macos(interval_min: int) -> None:
    if shutil.which("launchctl") is None:
        print("launchctl을 찾을 수 없습니다 (macOS가 아닌 것 같습니다).")
        sys.exit(1)

    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agents_dir / "com.aitemplate.orchestrator.plist"

    out_log = REPO_DIR / "state" / "launchd.out.log"
    err_log = REPO_DIR / "state" / "launchd.err.log"

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.aitemplate.orchestrator</string>
    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON}</string>
        <string>{ORCH}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{REPO_DIR}</string>
    <key>StartInterval</key>
    <integer>{interval_min * 60}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{out_log}</string>
    <key>StandardErrorPath</key>
    <string>{err_log}</string>
</dict>
</plist>
"""
    plist_path.write_text(plist, encoding="utf-8")

    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    result = subprocess.run(["launchctl", "load", "-w", str(plist_path)], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"launchctl load 실패: {result.stderr}")
        sys.exit(1)

    print("설치 완료 (launchd).")
    print("  상태 확인 : launchctl list | grep aitemplate")
    print(f"  로그 확인 : tail -f {out_log}")
    print(f"  제거      : launchctl unload {plist_path}")


def install_windows(interval_min: int) -> None:
    if shutil.which("schtasks") is None:
        print("schtasks.exe를 찾을 수 없습니다 (Windows가 아닌 것 같습니다).")
        sys.exit(1)

    task_name = "AITemplateOrchestrator"
    command = f'"{PYTHON}" "{ORCH}"'

    subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"], capture_output=True)
    result = subprocess.run(
        [
            "schtasks", "/Create", "/F",
            "/SC", "MINUTE", "/MO", str(interval_min),
            "/TN", task_name,
            "/TR", command,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("작업 스케줄러 등록 실패:")
        print(result.stdout)
        print(result.stderr)
        print()
        print("일반 명령 프롬프트/PowerShell에서 실패했다면 관리자 권한으로 다시 시도해보거나,")
        print("작업 스케줄러(Task Scheduler) GUI에서 아래 내용으로 수동 등록하세요:")
        print(f"  프로그램/스크립트: {PYTHON}")
        print(f"  인수 추가        : {ORCH}")
        print(f"  트리거           : {interval_min}분마다 반복")
        sys.exit(1)

    print("설치 완료 (Windows 작업 스케줄러).")
    print(f"  상태 확인 : schtasks /Query /TN {task_name} /V /FO LIST")
    print(f"  즉시 실행 : schtasks /Run /TN {task_name}")
    print(f"  제거      : schtasks /Delete /TN {task_name} /F")
    print(f"  로그 확인 : {REPO_DIR / 'state' / 'orchestrator.log'}")


def main() -> None:
    check_requirements()
    (REPO_DIR / "state").mkdir(exist_ok=True)

    interval_min = common.SETTINGS.get("CYCLE_INTERVAL_MIN", 5)
    os_name = common.get_os()

    print(f"감지된 OS: {os_name}\n")

    if os_name == "linux":
        install_linux(interval_min)
    elif os_name == "macos":
        install_macos(interval_min)
    elif os_name == "windows":
        install_windows(interval_min)
    else:
        print("지원하지 않는 OS입니다.")
        print(f"수동으로 다음 명령을 원하는 스케줄러에 {interval_min}분 간격으로 등록하세요:")
        print(f"  {PYTHON} {ORCH}")
        sys.exit(1)

    print()
    print(f'작업 추가        : {PYTHON} {SCRIPTS_DIR / "add_task.py"} "작업 설명"')
    print(f'프로젝트 통째로  : {PYTHON} {SCRIPTS_DIR / "plan_project.py"} "프로젝트 설명"')
    print(f'한 번에 끝까지   : {PYTHON} {SCRIPTS_DIR / "run_project.py"} "프로젝트 설명"')


if __name__ == "__main__":
    main()
