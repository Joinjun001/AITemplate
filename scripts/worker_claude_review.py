#!/usr/bin/env python3
"""리뷰 워커: 구현자와 완전히 분리된 새 Claude 세션에서, diff만 보고
승인/반려를 판단한다. 절대로 --continue/--resume 으로 구현 세션을 이어받지
않는다(자기가 짠 코드를 관대하게 봐주는 확증편향을 막기 위해)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import common  # noqa: E402
import task_queue as q  # noqa: E402

VERDICT_RE = re.compile(r'\{[^{}]*"verdict"[^{}]*\}', re.DOTALL)


def run(task_id: str) -> int:
    task = q.get(task_id)
    if not task:
        common.log(f"worker_claude_review: 작업을 찾을 수 없음: {task_id}")
        return 1

    desc = task["desc"]
    branch = f"task/{task_id}"
    repo = common.REPO_DIR
    base = common.SETTINGS.get("BASE_BRANCH", "main")

    rc, diff = common.run_cli(["git", "diff", f"{base}..{branch}"], cwd=repo)
    if not diff.strip():
        common.log(f"리뷰할 diff가 없음 ({task_id}) -> todo로 되돌림")
        q.bump_retry(task_id)
        return 0

    persona = (common.PROMPTS_DIR / "reviewer_persona.md").read_text(encoding="utf-8")
    prompt = f"""{persona}

# 작업 명세
{desc}

# diff (task/{task_id} vs {base})
```diff
{diff}
```

반드시 아래 JSON 형식으로만 답하라. 다른 텍스트/설명은 절대 출력하지 마라.
{{"verdict": "approve 또는 changes_requested", "comments": ["..."]}}"""

    # 구현자와 달리 리뷰어는 파일을 고칠 필요가 전혀 없다 — diff 텍스트만 보고
    # JSON 하나만 내면 되는 순수 텍스트 판단이라 plan_project.py와 같은 이유로
    # --dangerously-skip-permissions를 안 준다. 실제로 이 플래그를 켠 채로
    # 돌려보니, Claude가 프롬프트에 준 diff를 안 믿고 자기가 직접 git 명령을
    # 실행해서 "현재 작업 디렉터리"(직전 사이클이 마지막으로 체크아웃해둔,
    # 리뷰 대상과 무관한 다른 브랜치)를 들여다보고 엉뚱한 답을 반복하는
    # 문제가 실제로 발생했다. 툴 실행 권한 자체를 안 주면 프롬프트에 준
    # 텍스트만으로 판단하도록 강제된다.
    # 프롬프트(diff 전체 포함)는 argv가 아니라 stdin으로 넘긴다 — diff가 큰
    # 작업을 리뷰할 때 프롬프트를 인자로 그대로 넘겼다가 Windows에서
    # "명령줄이 너무 깁니다" 오류로 리뷰가 통째로 실패한 적이 있다.
    rc, out = common.run_cli(common.claude_cli_argv(), cwd=repo, input_text=prompt)

    if common.detect_limit_and_set_cooldown(out, "claude", common.SETTINGS["COOLDOWN_MIN_CLAUDE"]):
        common.log(f"Claude 쿨다운 감지(리뷰, {task_id}) -> in_review 유지, 다음 사이클에 재시도")
        return 0

    if rc == 127:
        common.log(
            f"⚠️ claude 명령을 찾을 수 없어 리뷰를 건너뜁니다 ({task_id}, 환경/PATH 문제로 보임). "
            f"PATH={os.environ.get('PATH', '')[:400]}"
        )
        return 1

    if rc != 0:
        common.log(f"리뷰 실행 실패 ({task_id}): {out[-500:]}")
        return 1

    verdict = None
    comments: list[str] = []
    m = VERDICT_RE.search(out)
    if m:
        try:
            parsed = json.loads(m.group(0))
            verdict = parsed.get("verdict")
            comments = parsed.get("comments", [])
        except json.JSONDecodeError:
            pass

    if verdict == "approve":
        common.ensure_clean_repo(repo)
        rc, checkout_out = common.run_cli(["git", "checkout", base], cwd=repo)
        if rc != 0:
            common.log(f"{base} 체크아웃 실패 ({task_id}), 병합 보류: {checkout_out}")
            return 1
        rc, merge_out = common.run_cli(
            ["git", "merge", "--no-ff", branch, "-m", f"Merge {branch}: {desc}"], cwd=repo
        )
        if rc != 0:
            # 다른 작업이 먼저 병합되면서 main이 앞서가 있으면 충돌날 수 있다.
            # 그대로 두면 매 사이클 똑같은 충돌을 반복하며 영원히 멈추니, 병합을
            # 되돌리고 "최신 main 기준으로 다시 구현"하도록 todo로 돌려보낸다.
            common.log(f"병합 충돌 ({task_id}), merge abort 후 재작업으로 돌림: {merge_out[-500:]}")
            common.run_cli(["git", "merge", "--abort"], cwd=repo)
            q.update(
                task_id,
                status="todo",
                review_notes=[
                    f"다른 작업이 먼저 병합되면서 {base}와 충돌났습니다. "
                    f"최신 {base} 기준으로 다시 구현해주세요."
                ],
                retries=task.get("retries", 0) + 1,
            )
            return 0
        rc, branch_out = common.run_cli(["git", "branch", "-d", branch], cwd=repo)
        if rc != 0:
            common.log(f"작업 브랜치 삭제 실패 ({task_id}, 무시하고 계속): {branch_out}")
        q.update(task_id, status="done")
        common.log(f"리뷰 승인 -> main 병합 완료: {task_id}")
    elif verdict == "changes_requested":
        q.update(
            task_id,
            status="todo",
            review_notes=comments,
            retries=task.get("retries", 0) + 1,
        )
        common.log(f"리뷰 반려 -> 재작업 큐로: {task_id}")
    else:
        common.log(f"리뷰 응답 파싱 실패 ({task_id}), 출력 일부: {out[-500:]}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용법: worker_claude_review.py <task_id>")
        sys.exit(1)
    sys.exit(run(sys.argv[1]))
