#!/usr/bin/env bash
# tasks/queue.jsonl (한 줄에 JSON 객체 하나, JSONL 포맷) 조작 헬퍼
# common.sh 를 먼저 source 했다는 가정 하에 QUEUE_FILE 변수를 사용합니다.

# id로 task 하나 조회
queue_get() {
  local id="$1"
  jq -c --arg id "$id" 'select(.id == $id)' "$QUEUE_FILE" 2>/dev/null | head -1
}

# status == "todo" 인 작업 중 맨 위(가장 오래된) 하나
queue_next_todo() {
  jq -c 'select(.status == "todo")' "$QUEUE_FILE" 2>/dev/null | head -1
}

# status == "in_review" 인 작업 중 맨 위 하나
queue_next_review() {
  jq -c 'select(.status == "in_review")' "$QUEUE_FILE" 2>/dev/null | head -1
}

# 새 작업 추가
# queue_add '{"id":"task-1","desc":"...","complexity":"simple","status":"todo","assignee":null,"retries":0,"review_notes":""}'
queue_add() {
  local json="$1"
  echo "$json" >> "$QUEUE_FILE"
}

# id로 지정된 task에 jq 표현식을 적용해서 갱신
# queue_update "task-1" '.status = "done"'
# queue_update "task-1" '.retries += 1'
queue_update() {
  local id="$1" jq_expr="$2"
  local tmp
  tmp=$(mktemp)
  jq -c --arg id "$id" 'if .id == $id then ('"$jq_expr"') else . end' "$QUEUE_FILE" > "$tmp"
  mv "$tmp" "$QUEUE_FILE"
}
