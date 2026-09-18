#!/usr/bin/env python3
"""프로젝트 설명 하나를 Claude에게 던져서 여러 개의 작업으로 쪼개고,
그 작업들을 한 번에 tasks/queue.jsonl 에 추가한다.

이 이후로는 orchestrator.py(스케줄러가 주기적으로 실행)가 큐를 처음부터
끝까지 알아서 처리한다 — 사람이 작업을 하나씩 add_task.py로 넣을 필요가 없다.

사용법:
  python scripts/plan_project.py "할일 관리 REST API 서버를 Flask + SQLite로 만들어줘. ..."
  python scripts/plan_project.py --file project_spec.txt
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import common  # noqa: E402
import task_queue as q  # noqa: E402

# 출력에서 가장 마지막에 나오는 최상위 JSON 배열을 찾는다(모델이 앞에 군더더기
# 텍스트를 조금 붙이는 경우에도 최대한 견고하게 파싱하기 위함).
ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def plan(description: str) -> list[dict]:
    common.warn_dangerous_env()
    persona = (common.PROMPTS_DIR / "planner_persona.md").read_text(encoding="utf-8")
    prompt = f"""{persona}

# 프로젝트 설명
{description}"""

    # 계획 단계는 순수 텍스트 추론만 필요하므로 --dangerously-skip-permissions를
    # 주지 않는다 (파일을 건드릴 권한 자체를 안 준다).
    rc, out = common.run_cli(common.claude_cli_argv(prompt), cwd=common.REPO_DIR)
    if rc != 0:
        print(f"[plan] Claude 실행 실패: {out[-800:]}")
        sys.exit(1)

    m = ARRAY_RE.search(out)
    if not m:
        print("[plan] 출력에서 JSON 배열을 찾지 못했습니다. 원본 출력:\n")
        print(out)
        sys.exit(1)

    try:
        tasks = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"[plan] JSON 파싱 실패: {e}\n원본 출력:\n{out}")
        sys.exit(1)

    if not isinstance(tasks, list):
        print(f"[plan] 배열이 아닌 값이 반환되었습니다: {tasks!r}")
        sys.exit(1)

    return tasks


def enqueue(tasks: list[dict]) -> list[tuple[str, str, str]]:
    """plan()이 반환한 작업 배열을 큐에 순서대로 추가하고, 추가된
    (task_id, complexity, desc) 목록을 반환한다. plan_project.py와
    run_project.py가 공통으로 쓴다."""
    added: list[tuple[str, str, str]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        desc = t.get("desc") or t.get("description")
        if not desc:
            continue
        complexity = t.get("complexity")
        if complexity not in ("simple", "complex"):
            complexity = "complex"  # 애매하면 더 신중한 쪽(Claude)으로

        task_id = q.new_id()
        q.add(
            {
                "id": task_id,
                "desc": desc,
                "complexity": complexity,
                "status": "todo",
                "assignee": None,
                "retries": 0,
                "review_notes": "",
            }
        )
        added.append((task_id, complexity, desc))
    return added


def main() -> int:
    if len(sys.argv) < 2:
        print('사용법: plan_project.py "프로젝트 설명" 또는 plan_project.py --file <스펙파일>')
        return 1

    if sys.argv[1] == "--file":
        if len(sys.argv) < 3:
            print("사용법: plan_project.py --file <스펙파일 경로>")
            return 1
        description = Path(sys.argv[2]).read_text(encoding="utf-8")
    else:
        description = sys.argv[1]

    print("[plan] Claude로 프로젝트를 작업 단위로 분해하는 중... (시간이 좀 걸릴 수 있습니다)")
    tasks = plan(description)

    if not tasks:
        print("[plan] 빈 작업 목록이 반환되었습니다. 프로젝트 설명을 좀 더 구체적으로 써서 다시 시도하세요.")
        return 1

    added = enqueue(tasks)
    skipped = len(tasks) - len(added)

    print(f"\n[plan] {len(added)}개 작업이 큐에 추가되었습니다"
          + (f" ({skipped}개는 형식이 이상해서 건너뜀)" if skipped else "") + ":\n")
    for task_id, complexity, desc in added:
        print(f"  - [{complexity:7s}] {task_id}: {desc}")

    print("\n다음 스케줄러 사이클부터 순서대로 자동 처리됩니다.")
    print("한 번 실행으로 완성까지 끝까지 지켜보고 싶으면 대신 run_project.py를 쓰세요:")
    print(f'  python scripts/run_project.py "{description[:60]}{"..." if len(description) > 60 else ""}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
