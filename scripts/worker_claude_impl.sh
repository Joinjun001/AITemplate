#!/usr/bin/env bash
# 복잡한 구현 워커: Claude Code CLI가 직접 파일을 수정하고 브랜치에 커밋한다.
# ⚠️ 구독(Pro/Max) 로그인 상태로만 실행하세요. ANTHROPIC_API_KEY 가 설정돼 있으면
#    종량제 API로 과금되니, 이 스크립트를 돌리는 셸/systemd 유닛에는
#    ANTHROPIC_API_KEY 를 절대 넣지 마세요.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$DIR/lib/queue.sh"

TASK_ID="${1:?사용법: worker_claude_impl.sh <task_id>}"
task_json="$(queue_get "$TASK_ID")"
if [ -z "$task_json" ]; then
  log "worker_claude_impl: 작업을 찾을 수 없음: $TASK_ID"
  exit 1
fi

desc="$(echo "$task_json" | jq -r '.desc')"
review_notes="$(echo "$task_json" | jq -r '.review_notes // empty')"
branch="task/$TASK_ID"

cd "$REPO_DIR"
git checkout main >/dev/null 2>&1 || true
git checkout -B "$branch" main

extra=""
if [ -n "$review_notes" ] && [ "$review_notes" != "null" ]; then
  extra="

이전 리뷰에서 아래와 같은 수정 요청이 있었다. 반드시 반영해라:
$review_notes"
fi

prompt="$(cat "$PROMPTS_DIR/implementer_persona.md")

작업 ID: $TASK_ID
작업 설명:
$desc
$extra"

output="$(claude -p "$prompt" --dangerously-skip-permissions 2>&1)"
status=$?

if detect_limit_and_cooldown "$output" "$STATE_DIR/claude_until" "$DEFAULT_COOLDOWN_MIN_CLAUDE"; then
  log "Claude 쿨다운 감지 ($TASK_ID) -> todo로 유지"
  queue_update "$TASK_ID" '.status = "todo"'
  exit 0
fi

if [ $status -ne 0 ]; then
  log "Claude 실행 실패 ($TASK_ID): $(echo "$output" | tail -5)"
  queue_update "$TASK_ID" '.status = "todo" | .retries += 1'
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -m "[claude] $TASK_ID: $desc" >/dev/null
  queue_update "$TASK_ID" '.status = "in_review" | .assignee = "claude"'
  log "Claude 구현 완료, 리뷰 대기로 전환: $TASK_ID"
else
  log "Claude가 변경사항을 만들지 않음 ($TASK_ID) -> 재시도 카운트 증가"
  queue_update "$TASK_ID" '.status = "todo" | .retries += 1'
fi
