#!/usr/bin/env bash
# 큐에 새 작업을 추가하는 헬퍼.
# 사용법:
#   ./scripts/add_task.sh "로그인 폼 유효성 검사 버그 수정"                 -> Gemini에게 복잡도 자동 분류를 맡김
#   ./scripts/add_task.sh "결제 모듈 리팩터링" complex                      -> 복잡도를 직접 지정
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$DIR/lib/queue.sh"

DESC="${1:?사용법: add_task.sh \"작업 설명\" [simple|complex]}"
COMPLEXITY="${2:-}"

if [ -z "$COMPLEXITY" ]; then
  echo "[triage] Gemini로 복잡도 분류 중..."
  raw="$(gemini -p "다음 작업이 '대량이거나 단순 반복적인 작업'이면 simple, '복잡한 설계 판단이 필요한 작업'이면 complex 라고 정확히 한 단어로만 답해라: $DESC" 2>&1)"
  case "$raw" in
    *simple*)  COMPLEXITY="simple" ;;
    *complex*) COMPLEXITY="complex" ;;
    *) echo "[triage] 판단 실패, 안전하게 complex로 분류: $raw"; COMPLEXITY="complex" ;;
  esac
fi

ID="task-$(date +%Y%m%d%H%M%S)"
jq -nc --arg id "$ID" --arg desc "$DESC" --arg complexity "$COMPLEXITY" \
  '{id:$id, desc:$desc, complexity:$complexity, status:"todo", assignee:null, retries:0, review_notes:""}' \
  >> "$QUEUE_FILE"

echo "추가됨: $ID (complexity=$COMPLEXITY)"
