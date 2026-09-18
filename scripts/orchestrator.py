#!/usr/bin/env python3
"""메인 오케스트레이터. OS 스케줄러(systemd timer / launchd / 작업 스케줄러)가
주기적으로 이 스크립트를 한 번씩 실행합니다.

1) Claude 쿨다운이 아니면 리뷰 대기(in_review) 작업을 리뷰
2) todo 작업을 하나 꺼내서 complexity에 따라 Gemini/Claude 워커에 라우팅
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import common  # noqa: E402
import task_queue as q  # noqa: E402


def _run_worker(script_name: str, task_id: str) -> None:
    script = SCRIPTS_DIR / script_name
    proc = subprocess.run([sys.executable, str(script), task_id])
    if proc.returncode != 0:
        common.log(f"{script_name} 비정상 종료 (task {task_id}, code {proc.returncode})")


def main() -> int:
    try:
        common.acquire_lock()
    except common.AlreadyRunning as e:
        common.log(str(e))
        return 0

    try:
        common.log("===== orchestrator 사이클 시작 =====")

        # 1) 리뷰 대기 작업 (구현자와 분리된 새 Claude 세션에서 diff만 보고 판단)
        if not common.is_cooling_down("claude"):
            review_task = q.next_with_status("in_review")
            if review_task:
                common.log(f"리뷰 실행: {review_task['id']}")
                _run_worker("worker_claude_review.py", review_task["id"])
            else:
                common.log("리뷰 대기 작업 없음")
        else:
            common.log("Claude 쿨다운 중이라 리뷰는 건너뜀")

        # 2) 새 구현 작업
        todo_task = q.next_with_status("todo")
        if not todo_task:
            common.log("todo 작업 없음")
            common.log("===== orchestrator 사이클 종료 =====")
            return 0

        task_id = todo_task["id"]
        complexity = todo_task.get("complexity", "complex")
        retries = todo_task.get("retries", 0)
        max_retries = common.SETTINGS["MAX_RETRIES"]

        if retries >= max_retries:
            common.log(f"재시도 한도({max_retries}) 초과 -> blocked 처리: {task_id} (review_notes 확인 후 수동 조치)")
            q.update(task_id, status="blocked")
            common.log("===== orchestrator 사이클 종료 =====")
            return 0

        q.update(task_id, status="in_progress")

        if complexity == "simple":
            if common.is_cooling_down("gemini"):
                common.log(f"Gemini 쿨다운 중, {task_id} 는 todo로 되돌림")
                q.update(task_id, status="todo")
            else:
                common.log(f"Gemini 워커 실행: {task_id}")
                _run_worker("worker_gemini.py", task_id)
        else:
            if common.is_cooling_down("claude"):
                common.log(f"Claude 쿨다운 중, {task_id} 는 todo로 되돌림")
                q.update(task_id, status="todo")
            else:
                common.log(f"Claude 구현 워커 실행: {task_id}")
                _run_worker("worker_claude_impl.py", task_id)

        common.log("===== orchestrator 사이클 종료 =====")
        return 0
    finally:
        common.release_lock()


if __name__ == "__main__":
    sys.exit(main())
