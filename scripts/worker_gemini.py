#!/usr/bin/env python3
"""대량/단순 작업 워커: Gemini 계열 CLI(기본값 Antigravity CLI = agy)가 직접
파일을 수정하고 브랜치에 커밋한다. 실제 실행 파일 이름은
config/settings.json 의 GEMINI_CLI_CMD 로 바꿀 수 있다."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import common  # noqa: E402
import task_queue as q  # noqa: E402


def run(task_id: str) -> int:
    task = q.get(task_id)
    if not task:
        common.log(f"worker_gemini: 작업을 찾을 수 없음: {task_id}")
        return 1

    desc = task["desc"]
    branch = f"task/{task_id}"
    repo = common.REPO_DIR

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

    persona = (common.PROMPTS_DIR / "gemini_worker_persona.md").read_text(encoding="utf-8")
    prompt = f"""{persona}

작업 ID: {task_id}
작업 설명:
{desc}

이 저장소(현재 디렉터리)의 관련 파일을 직접 열어보고 필요한 변경을 적용해줘.
마지막에 변경한 파일 목록과 이유를 한국어로 간단히 요약해줘."""

    argv = common.gemini_cli_argv(prompt, skip_permissions=True)
    rc, out = common.run_cli(argv, cwd=repo)

    if common.detect_limit_and_set_cooldown(out, "gemini", common.SETTINGS["COOLDOWN_MIN_GEMINI"]):
        common.log(f"Gemini({argv[0]}) 쿨다운 감지 ({task_id}) -> todo로 유지")
        q.update(task_id, status="todo")
        return 0

    if rc != 0:
        common.log(f"Gemini({argv[0]}) 실행 실패 ({task_id}): {out[-500:]}")
        q.bump_retry(task_id)
        return 1

    _, status_out = common.run_cli(["git", "status", "--porcelain"], cwd=repo)
    if status_out.strip():
        common.run_cli(["git", "add", "-A"], cwd=repo)
        common.run_cli(["git", "commit", "-m", f"[gemini] {task_id}: {desc}"], cwd=repo)
        q.update(task_id, status="in_review", assignee="gemini")
        common.log(f"Gemini 작업 완료, 리뷰 대기로 전환: {task_id}")
    else:
        common.log(f"Gemini가 변경사항을 만들지 않음 ({task_id}) -> 재시도 카운트 증가")
        q.bump_retry(task_id)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: worker_gemini.py <task_id>")
        sys.exit(1)
    sys.exit(run(sys.argv[1]))
