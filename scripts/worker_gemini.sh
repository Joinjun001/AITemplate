#!/usr/bin/env bash
# 대량/단순 작업 워커: Gemini CLI가 직접 파일을 수정하고 브랜치에 커밋한다.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$DIR/lib/queue.sh"

TASK_ID="${1:?사용법: worker_gemini.sh <task_id>}"
task_json="$(queue_get "$TASK_ID")"
if [ -z "$task_json" ]; then
  log "worker_gemini: 작업을 찾을 수 없음: $TASK_ID"
  exit 1
fi

desc="$(echo "$task_json" | jq -r '.desc')"
branch="task/$TASK_ID"

cd "$REPO_DIR"
git checkout main >/dev/null 2>&1 || true
git checkout -B "$branch" main

prompt="$(cat "$PROMPTS_DIR/gemini_worker_persona.md")

작업 ID: $TASK_ID
작업 설명:
$desc

이 저장소(현재 디렉터리)의 관련 파일을 직접 열어보고 필요한 변경을 적용해줘.
마지막에 변경한 파일 목록과 이유를 한국어로 간단히 요약해줘."

output="$(gemini -p "$prompt" 2>&1)"
status=$?

if detect_limit_and_cooldown "$output" "$STATE_DIR/gemini_until" "$DEFAULT_COOLDOWN_MIN_GEMINI"; then
  log "Gemini 쿨다운 감지 ($TASK_ID) -> todo로 유지"
  queue_update "$TASK_ID" '.status = "todo"'
  exit 0
fi

if [ $status -ne 0 ]; then
  log "Gemini 실행 실패 ($TASK_ID): $(echo "$output" | tail -5)"
  queue_update "$TASK_ID" '.status = "todo" | .retries += 1'
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -m "[gemini] $TASK_ID: $desc" >/dev/null
  queue_update "$TASK_ID" '.status = "in_review" | .assignee = "gemini"'
  log "Gemini 작업 완료, 리뷰 대기로 전환: $TASK_ID"
else
  log "Gemini가 변경사항을 만들지 않음 ($TASK_ID) -> 재시도 카운트 증가"
  queue_update "$TASK_ID" '.status = "todo" | .retries += 1'
fi
