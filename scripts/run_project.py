#!/usr/bin/env python3
"""터미널에서 "한 번만" 실행하면, 프로젝트 설명을 작업으로 분해한 뒤
큐가 완전히 끝날 때까지(모든 작업이 done 또는 blocked가 될 때까지)
orchestrator 사이클을 이 프로세스 안에서 계속 돌리는 진입점.

install.py로 등록하는 백그라운드 스케줄러(systemd/launchd/작업 스케줄러)와
쓰임새가 다릅니다:

  - install.py     : 컴퓨터를 계속 켜두고 여러 프로젝트/작업을 몇 시간~며칠에
                      걸쳐 알아서 처리하게 하고 싶을 때 (백그라운드, 재부팅
                      후에도 유지, 5분 등 고정 간격으로 조금씩 진행)
  - run_project.py : 지금 이 터미널에서 프로젝트 하나를 통째로 맡기고, 다 될
                      때까지 지켜보거나 다른 일 하다가 돌아오고 싶을 때
                      (포그라운드로 계속 실행됨, Ctrl+C로 중단해도 큐 상태는
                      파일에 남아있어서 --resume으로 이어서 진행 가능)

같은 저장소에서 백그라운드 스케줄러가 이미 돌고 있어도 동시에 실행해도
안전합니다 (common.acquire_lock()의 파일 락이 겹치는 실행을 막아줍니다).
다만 로그가 섞여 보기 불편하니 실제로는 하나만 켜두는 걸 권장합니다.

사용법:
  python scripts/run_project.py "프로젝트 설명"
  python scripts/run_project.py --file project_spec.txt
  python scripts/run_project.py --resume   # 새로 계획하지 않고 기존 큐만 이어서 처리
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import common  # noqa: E402
import task_queue as q  # noqa: E402
import orchestrator  # noqa: E402
import plan_project  # noqa: E402

TERMINAL_STATUSES = ("done", "blocked")
STATUS_ORDER = ("todo", "in_progress", "in_review", "done", "blocked")


def _summary(tasks: list[dict]) -> str:
    if not tasks:
        return "(큐 비어있음)"
    counts: dict[str, int] = {}
    for t in tasks:
        s = t.get("status", "?")
        counts[s] = counts.get(s, 0) + 1
    parts = [f"{s}={counts[s]}" for s in STATUS_ORDER if counts.get(s)]
    extra = [f"{s}={n}" for s, n in counts.items() if s not in STATUS_ORDER]
    return " / ".join(parts + extra)


def _sleep_seconds_when_idle() -> float:
    """이번 사이클에서 아무 진전도 없었을 때 다음 시도까지 얼마나 쉴지 계산.
    claude/gemini 쿨다운 중이면 그 쿨다운이 풀리는 시각까지(최대 10분 단위로
    끊어서) 재우고, 쿨다운도 아니면 그냥 짧게(RUN_LOOP_POLL_SEC) 재운다 —
    쿨다운이 아닌데 진전이 없다면 보통 일시적인 실행 실패 재시도 대기 상황."""
    remaining = [
        secs
        for secs in (common.seconds_until_cooldown_clears("claude"), common.seconds_until_cooldown_clears("gemini"))
        if secs is not None
    ]
    poll = common.SETTINGS.get("RUN_LOOP_POLL_SEC", 20)
    if not remaining:
        return poll
    return max(poll, min(min(remaining), 600))


def run(description: str | None) -> int:
    common.warn_dangerous_env()
    if description:
        print("[run] Claude로 프로젝트를 작업 단위로 분해하는 중... (시간이 좀 걸릴 수 있습니다)")
        tasks = plan_project.plan(description)
        if not tasks:
            print("[run] 빈 작업 목록이 반환되었습니다. 프로젝트 설명을 좀 더 구체적으로 써서 다시 시도하세요.")
            return 1
        added = plan_project.enqueue(tasks)
        print(f"[run] {len(added)}개 작업이 큐에 추가되었습니다:")
        for task_id, complexity, desc in added:
            print(f"  - [{complexity:7s}] {task_id}: {desc}")

    base = common.SETTINGS.get("BASE_BRANCH", "main")
    print(f"\n[run] 기준 브랜치: {base}")
    print("[run] 큐의 모든 작업이 done/blocked가 될 때까지 계속 진행합니다. 중단하려면 Ctrl+C.")

    cycle = 0
    try:
        while True:
            before = q.all_tasks()
            if not before:
                print("[run] 큐가 비어 있습니다. 처리할 작업이 없습니다.")
                break
            if all(t.get("status") in TERMINAL_STATUSES for t in before):
                break

            cycle += 1
            print(f"\n[run] ----- 사이클 {cycle} ({_summary(before)}) -----")
            orchestrator.main()

            after = q.all_tasks()
            if all(t.get("status") in TERMINAL_STATUSES for t in after):
                break
            progressed = _summary(after) != _summary(before)
            time.sleep(common.SETTINGS.get("RUN_LOOP_POLL_SEC", 20) if progressed else _sleep_seconds_when_idle())
    except KeyboardInterrupt:
        print(
            "\n[run] 중단되었습니다. 큐 상태는 tasks/queue.jsonl에 그대로 저장되어 있으니, "
            "나중에 'python scripts/run_project.py --resume'으로 이어서 진행할 수 있습니다."
        )
        return 130

    final = q.all_tasks()
    done = [t for t in final if t.get("status") == "done"]
    blocked = [t for t in final if t.get("status") == "blocked"]
    print(f"\n[run] ===== 종료: 완료 {len(done)}건, 차단(blocked) {len(blocked)}건 =====")
    if blocked:
        print("[run] 아래 작업은 재시도 한도를 넘겨 자동 처리가 멈췄습니다. review_notes를 보고 수동 조치하세요:")
        for t in blocked:
            print(f"  - {t['id']}: {t['desc']}")
            notes = t.get("review_notes")
            if notes:
                print(f"    review_notes: {notes}")
        return 1

    print(f"[run] 모든 작업이 완료되었습니다. '{base}' 브랜치에서 git log --oneline 으로 전체 히스토리를 확인하세요.")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print('사용법: run_project.py "프로젝트 설명" | run_project.py --file <경로> | run_project.py --resume')
        return 1

    arg = sys.argv[1]
    if arg == "--resume":
        return run(None)
    if arg == "--file":
        if len(sys.argv) < 3:
            print("사용법: run_project.py --file <스펙파일 경로>")
            return 1
        description = Path(sys.argv[2]).read_text(encoding="utf-8")
        return run(description)
    return run(arg)


if __name__ == "__main__":
    sys.exit(main())
