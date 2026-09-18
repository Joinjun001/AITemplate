#!/usr/bin/env python3
"""큐에 새 작업을 추가하는 헬퍼.

사용법:
  python scripts/add_task.py "로그인 폼 유효성 검사 버그 수정"          # 복잡도는 Gemini가 자동 분류
  python scripts/add_task.py "결제 모듈 리팩터링" complex               # 복잡도 직접 지정
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import common  # noqa: E402
import task_queue as q  # noqa: E402


def classify_with_gemini(desc: str) -> str:
    print(f"[triage] Gemini({common.SETTINGS.get('GEMINI_CLI_CMD', 'agy')})로 복잡도 분류 중...")
    prompt = (
        "다음 작업이 '대량이거나 단순 반복적인 작업'이면 simple, "
        f"'복잡한 설계 판단이 필요한 작업'이면 complex 라고 정확히 한 단어로만 답해라: {desc}"
    )
    rc, out = common.run_cli(common.gemini_cli_argv(), input_text=prompt)
    low = out.lower()
    if rc == 0 and "simple" in low:
        return "simple"
    if rc == 0 and "complex" in low:
        return "complex"
    print(f"[triage] 판단 실패, 안전하게 complex로 분류합니다. (출력: {out[:200]!r})")
    return "complex"


def main() -> int:
    if len(sys.argv) < 2:
        print('사용법: add_task.py "작업 설명" [simple|complex]')
        return 1

    desc = sys.argv[1]
    complexity = sys.argv[2] if len(sys.argv) > 2 else ""
    if complexity not in ("simple", "complex"):
        complexity = classify_with_gemini(desc)

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
    print(f"추가됨: {task_id} (complexity={complexity})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
