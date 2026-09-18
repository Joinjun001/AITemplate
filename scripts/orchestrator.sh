#!/usr/bin/env bash
# 메인 오케스트레이터: systemd 타이머가 주기적으로 이 스크립트를 실행합니다.
# 1) Claude 쿨다운 아니면 리뷰 대기(in_review) 작업을 리뷰
# 2) todo 작업을 하나 꺼내서 complexity에 따라 Gemini/Claude 워커에 라우팅
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$DIR/lib/queue.sh"

# 동시 실행 방지 (이미 이전 사이클이 안 끝났으면 이번 사이클은 건너뜀)
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "이미 실행 중인 orchestrator가 있어 이번 사이클은 건너뜀"
  exit 0
fi

log "===== orchestrator 사이클 시작 ====="

# --- 1) 리뷰 대기 작업 처리 (Claude 리뷰어, 구현자와 별도 세션) ---
if ! is_cooling_down "$STATE_DIR/claude_until"; then
  review_task="$(queue_next_review)"
  if [ -n "$review_task" ]; then
    task_id="$(echo "$review_task" | jq -r '.id')"
    log "리뷰 실행: $task_id"
    "$DIR/worker_claude_review.sh" "$task_id" || log "리뷰 워커 오류: $task_id (다음 사이클에 재시도)"
  else
    log "리뷰 대기 작업 없음"
  fi
else
  log "Claude 쿨다운 중이라 리뷰는 건너뜀"
fi

# --- 2) 새 구현 작업 처리 ---
todo_task="$(queue_next_todo)"
if [ -z "$todo_task" ]; then
  log "todo 작업 없음"
  log "===== orchestrator 사이클 종료 ====="
  exit 0
fi

task_id="$(echo "$todo_task" | jq -r '.id')"
complexity="$(echo "$todo_task" | jq -r '.complexity')"
retries="$(echo "$todo_task" | jq -r '.retries')"

if [ "$retries" -ge "$MAX_RETRIES" ]; then
  log "재시도 한도($MAX_RETRIES) 초과 -> blocked 처리: $task_id (review_notes 확인 후 수동 조치 필요)"
  queue_update "$task_id" '.status = "blocked"'
  log "===== orchestrator 사이클 종료 ====="
  exit 0
fi

queue_update "$task_id" '.status = "in_progress"'

if [ "$complexity" = "simple" ]; then
  if is_cooling_down "$STATE_DIR/gemini_until"; then
    log "Gemini 쿨다운 중, $task_id 는 todo로 되돌림"
    queue_update "$task_id" '.status = "todo"'
  else
    log "Gemini 워커 실행: $task_id"
    "$DIR/worker_gemini.sh" "$task_id" || log "Gemini 워커 오류: $task_id (다음 사이클에 재시도)"
  fi
else
  if is_cooling_down "$STATE_DIR/claude_until"; then
    log "Claude 쿨다운 중, $task_id 는 todo로 되돌림"
    queue_update "$task_id" '.status = "todo"'
  else
    log "Claude 구현 워커 실행: $task_id"
    "$DIR/worker_claude_impl.sh" "$task_id" || log "Claude 워커 오류: $task_id (다음 사이클에 재시도)"
  fi
fi

log "===== orchestrator 사이클 종료 ====="
