#!/usr/bin/env python3
"""복잡한 구현 워커: Claude Code CLI가 직접 파일을 수정하고 브랜치에 커밋한다.

⚠️ 구독(Pro/Max) 로그인 상태로만 실행하세요. 이 스크립트를 실행하는 프로세스의
   환경에 ANTHROPIC_API_KEY 가 설정돼 있으면 종량제 API로 과금되니, systemd
   유닛/launchd plist/작업 스케줄러 어디에도 그 값을 넣지 마세요.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import common  # noqa: E402
import task_queue as q  # noqa: E402


def _format_review_notes(notes) -> str:
    if not notes:
        return ""
    if isinstance(notes, list):
        return "\n".join(f"- {c}" for c in notes)
    return str(notes)


def run(task_id: str) -> int:
    task = q.get(task_id)
    if not task:
        common.log(f"worker_claude_impl: 작업을 찾을 수 없음: {task_id}")
        return 1

    desc = task["desc"]
    review_notes = _format_review_notes(task.get("review_notes"))
    branch = f"task/{task_id}"
    repo = common.REPO_DIR

    common.ensure_clean_repo(repo)
    rc, out = common.run_cli(["git", "checkout", "main"], cwd=repo)
    if rc != 0:
        common.log(f"main 체크아웃 실패 ({task_id}): {out}")
        q.update(task_id, status="todo")
        return 1
    rc, out = common.run_cli(["git", "checkout", "-B", branch, "main"], cwd=repo)
    if rc != 0:
        common.log(f"브랜치 생성 실패 ({task_id}): {out}")
        q.update(task_id, status="todo")
        return 1

    persona = (common.PROMPTS_DIR / "implementer_persona.md").read_text(encoding="utf-8")
    extra = ""
    if review_notes:
        extra = f"\n\n이전 리뷰에서 아래와 같은 수정 요청이 있었다. 반드시 반영해라:\n{review_notes}"

    prompt = f"""{persona}

작업 ID: {task_id}
작업 설명:
{desc}{extra}"""

    rc, out = common.run_cli(["claude", "-p", prompt, "--dangerously-skip-permissions"], cwd=repo)

    if common.detect_limit_and_set_cooldown(out, "claude", common.SETTINGS["COOLDOWN_MIN_CLAUDE"]):
        common.log(f"Claude 쿨다운 감지 ({task_id}) -> todo로 유지")
        q.update(task_id, status="todo")
        return 0

    if rc != 0:
        common.log(f"Claude 실행 실패 ({task_id}): {out[-500:]}")
        q.bump_retry(task_id)
        return 1

    _, status_out = common.run_cli(["git", "status", "--porcelain"], cwd=repo)
    if status_out.strip():
        common.run_cli(["git", "add", "-A"], cwd=repo)
        common.run_cli(["git", "commit", "-m", f"[claude] {task_id}: {desc}"], cwd=repo)
        q.update(task_id, status="in_review", assignee="claude")
        common.log(f"Claude 구현 완료, 리뷰 대기로 전환: {task_id}")
    else:
        common.log(f"Claude가 변경사항을 만들지 않음 ({task_id}) -> 재시도 카운트 증가")
        q.bump_retry(task_id)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: worker_claude_impl.py <task_id>")
        sys.exit(1)
    sys.exit(run(sys.argv[1]))
