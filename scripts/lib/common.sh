#!/usr/bin/env bash
# 공통 설정 및 헬퍼 함수
# 이 파일은 orchestrator.sh / worker_*.sh 에서 source 해서 씁니다.

# --- 경로 설정 ---
# lib/common.sh 기준으로 REPO_DIR(=이 템플릿을 clone한 프로젝트 루트)를 계산
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$LIB_DIR/.." && pwd)"
REPO_DIR="$(cd "$SCRIPTS_DIR/.." && pwd)"

STATE_DIR="$REPO_DIR/state"
PROMPTS_DIR="$REPO_DIR/prompts"
QUEUE_FILE="$REPO_DIR/tasks/queue.jsonl"
LOG_FILE="$STATE_DIR/orchestrator.log"
LOCK_FILE="$STATE_DIR/orchestrator.lock"

mkdir -p "$STATE_DIR"
touch "$QUEUE_FILE" "$LOG_FILE"

# --- 설정값 (필요하면 config/settings.env 로 덮어쓰기) ---
MAX_RETRIES="${MAX_RETRIES:-3}"
DEFAULT_COOLDOWN_MIN_CLAUDE="${DEFAULT_COOLDOWN_MIN_CLAUDE:-300}" # 5시간 롤링 한도 기본값(분)
DEFAULT_COOLDOWN_MIN_GEMINI="${DEFAULT_COOLDOWN_MIN_GEMINI:-60}"

if [ -f "$REPO_DIR/config/settings.env" ]; then
  # shellcheck disable=SC1091
  source "$REPO_DIR/config/settings.env"
fi

# --- 로깅 ---
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# --- 쿨다운(리밋) 상태 확인/기록 ---
# 사용법: is_cooling_down "$STATE_DIR/claude_until"  -> 아직 리밋 안 풀렸으면 0(true), 풀렸으면 1(false)
is_cooling_down() {
  local state_file="$1"
  [ -f "$state_file" ] || return 1
  local until_epoch now
  until_epoch=$(cat "$state_file" 2>/dev/null || echo 0)
  now=$(date +%s)
  if [ "$until_epoch" -gt "$now" ]; then
    return 0
  else
    rm -f "$state_file"
    return 1
  fi
}

# CLI 출력에서 "사용량 한도" 관련 메시지를 감지해서 쿨다운 시각을 기록한다.
# ⚠️ Claude Code / Gemini CLI 가 실제로 내보내는 리밋 메시지 문구는 버전에 따라
#    바뀔 수 있습니다. 아래 grep 패턴이 안 맞으면 실제 메시지를 보고 수정하세요.
#
# 사용법: detect_limit_and_cooldown "$output" "$STATE_DIR/claude_until" "$DEFAULT_COOLDOWN_MIN_CLAUDE"
# 반환값: 리밋 메시지를 감지했으면 0(true), 아니면 1(false)
detect_limit_and_cooldown() {
  local output="$1" state_file="$2" default_minutes="$3"

  if ! echo "$output" | grep -qiE "usage limit|rate limit|quota|resets? (at|in)|try again (later|in)|429"; then
    return 1
  fi

  local reset_epoch=""
  local time_str
  time_str=$(echo "$output" | grep -oE '[0-9]{1,2}:[0-9]{2}[[:space:]]*(AM|PM|am|pm)?' | head -1)

  if [ -n "$time_str" ]; then
    reset_epoch=$(date -d "$time_str" +%s 2>/dev/null || echo "")
    # 오늘 그 시각이 이미 지났으면 이미 지난 값일 수 있으니 다음날로 보정하지 않고
    # 그냥 기본 쿨다운으로 대체(아래 fallback)한다 - 안전하게 더 짧게 자게 두는 쪽 선택.
  fi

  if [ -z "$reset_epoch" ] || [ "$reset_epoch" -le "$(date +%s)" ]; then
    reset_epoch=$(( $(date +%s) + default_minutes * 60 ))
  fi

  echo "$reset_epoch" > "$state_file"
  log "쿨다운 설정: $state_file -> $(date -d "@$reset_epoch" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "$reset_epoch")"
  return 0
}
