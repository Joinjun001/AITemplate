#!/usr/bin/env bash
# systemd --user 유닛을 설치하고 타이머를 활성화한다.
# 전제 조건: claude, gemini, jq, git, flock 이 PATH에 있어야 하고,
#            claude/gemini 모두 API 키가 아니라 구독/무료 로그인 상태여야 한다.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for cmd in claude gemini jq git flock systemctl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "필요한 명령어를 찾을 수 없습니다: $cmd" >&2
    exit 1
  fi
done

mkdir -p "$HOME/.config/systemd/user"

sed "s#__REPO_DIR__#$DIR#g" "$DIR/systemd/ai-orchestrator.service" \
  > "$HOME/.config/systemd/user/ai-orchestrator.service"
cp "$DIR/systemd/ai-orchestrator.timer" "$HOME/.config/systemd/user/ai-orchestrator.timer"

systemctl --user daemon-reload
systemctl --user enable --now ai-orchestrator.timer

echo ""
echo "설치 완료."
echo "상태 확인:   systemctl --user status ai-orchestrator.timer"
echo "다음 실행:   systemctl --user list-timers ai-orchestrator.timer"
echo "로그 확인:   journalctl --user -u ai-orchestrator.service -f"
echo "작업 추가:   $DIR/scripts/add_task.sh \"작업 설명\""
