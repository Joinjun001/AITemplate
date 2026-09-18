#!/usr/bin/env bash
# 리뷰 워커: 구현자와 완전히 분리된 새 Claude 세션에서, diff만 보고 승인/반려를 판단한다.
# 절대로 --continue / --resume 으로 구현 세션을 이어받지 않는다 (확증편향 방지).
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$DIR/lib/queue.sh"

TASK_ID="${1:?사용법: worker_claude_review.sh <task_id>}"
task_json="$(queue_get "$TASK_ID")"
if [ -z "$task_json" ]; then
  log "worker_claude_review: 작업을 찾을 수 없음: $TASK_ID"
  exit 1
fi

desc="$(echo "$task_json" | jq -r '.desc')"
branch="task/$TASK_ID"

cd "$REPO_DIR"
diff="$(git diff main.."$branch" 2>&1)"
if [ -z "$diff" ]; then
  log "리뷰할 diff가 없음 ($TASK_ID) -> todo로 되돌림"
  queue_update "$TASK_ID" '.status = "todo" | .retries += 1'
  exit 0
fi

prompt="$(cat "$PROMPTS_DIR/reviewer_persona.md")

# 작업 명세
$desc

# diff (task/$TASK_ID vs main)
\`\`\`diff
$diff
\`\`\`

반드시 아래 JSON 형식으로만 답하라. 다른 텍스트/설명은 절대 출력하지 마라.
{\"verdict\": \"approve\" 또는 \"changes_requested\", \"comments\": [\"...\"]}"

output="$(claude -p "$prompt" --dangerously-skip-permissions 2>&1)"
status=$?

if detect_limit_and_cooldown "$output" "$STATE_DIR/claude_until" "$DEFAULT_COOLDOWN_MIN_CLAUDE"; then
  log "Claude 쿨다운 감지 (리뷰, $TASK_ID) -> in_review로 유지, 다음 사이클에 재시도"
  exit 0
fi

if [ $status -ne 0 ]; then
  log "리뷰 실행 실패 ($TASK_ID): $(echo "$output" | tail -5)"
  exit 1
fi

verdict_json="$(echo "$output" | grep -oE '\{[^{}]*"verdict"[^{}]*\}' | tail -1)"
verdict="$(echo "$verdict_json" | jq -r '.verdict // empty' 2>/dev/null)"

if [ "$verdict" = "approve" ]; then
  git checkout main
  git merge --no-ff "$branch" -m "Merge $branch: $desc" >/dev/null
  git branch -d "$branch" >/dev/null 2>&1 || true
  queue_update "$TASK_ID" '.status = "done"'
  log "리뷰 승인 -> main 병합 완료: $TASK_ID"
elif [ "$verdict" = "changes_requested" ]; then
  comments="$(echo "$verdict_json" | jq -c '.comments // []' 2>/dev/null)"
  [ -z "$comments" ] && comments="[]"
  queue_update "$TASK_ID" ".status = \"todo\" | .retries += 1 | .review_notes = ($comments | tostring)"
  log "리뷰 반려 -> 재작업 큐로: $TASK_ID"
else
  log "리뷰 응답 파싱 실패 ($TASK_ID), 원본 출력 일부: $(echo "$output" | tail -5)"
  # 파싱 실패는 재시도 카운트를 올리지 않고 그대로 in_review 유지 (모델이 형식만 어겼을 수 있음)
fi
