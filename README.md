# AITemplate

컴퓨터가 켜져 있는 동안, **구독/무료 한도 안에서** Claude Code와 Gemini CLI를 조합해
작업 큐를 자동으로 처리하는 셀프호스팅 오케스트레이션 템플릿입니다.

- **Claude**: 복잡한 설계 판단이 필요한 구현 + 최종 코드 리뷰
- **Gemini**: 토큰이 넉넉한 대량/단순 작업 처리 (+ 선택적으로 작업 난이도 자동 분류)
- **systemd 타이머**: 사용량 한도(토큰) 소진으로 멈춘 작업을, 한도가 풀리는 대로 자동 재개

> 이 저장소는 실행 가능한 뼈대(스킬레톤)입니다. 실제 프로젝트 저장소 안에 그대로
> 복사해 넣거나, 이 저장소를 서브모듈/참고용으로 두고 스크립트 경로만 맞춰 쓰세요.

## 왜 이런 구조인가 (요약)

- Claude Code를 **구독(Pro/Max) 로그인**으로 쓰면 월정액 안에서 자동화해도 추가 과금이 없습니다.
  대신 5시간 롤링 한도에 걸리면 완전히 멈춥니다 — 이걸 systemd 타이머가 "한도 풀릴 때까지
  기다렸다가 자동 재개"로 해결합니다.
- Gemini CLI는 개인 구글 계정 로그인 기준 하루 1,000회 요청까지 무료입니다. 컨텍스트가 크고
  판단이 단순한 작업(반복 수정, 대량 파일 처리 등)을 여기로 보내면 Claude 쿼터를 아낄 수 있습니다.
- **비용 폭탄을 막으려면**: `ANTHROPIC_API_KEY` 환경변수를 이 스크립트를 실행하는 셸/systemd
  유닛에 절대 넣지 마세요. 넣는 순간 종량제 API 과금으로 전환됩니다. Extra Usage(종량제
  오버플로우)도 켜지 마세요. 두 CLI 모두 `claude login` / `gemini` 로그인으로 인증된 상태로만
  실행되어야 합니다.
- 리뷰는 **구현자와 완전히 분리된 새 세션**에서 diff만 보고 판단합니다(같은 대화를 이어가면
  자기가 짠 코드를 관대하게 봐주는 확증편향이 생기기 쉽습니다).

## 아키텍처

```
systemd timer (예: 5분마다, Persistent=true)
        │
        ▼
  scripts/orchestrator.sh   -- flock으로 중복 실행 방지
        │
        ├─ state/claude_until, state/gemini_until 로 쿨다운(한도) 확인
        │
        ▼
  tasks/queue.jsonl (todo / in_progress / in_review / done / blocked)
        │
   ┌────┴─────────────┐
   ▼                   ▼
worker_gemini.sh     worker_claude_impl.sh
(complexity=simple)  (complexity=complex)
   │                   │
   └─────────┬─────────┘
             ▼
   task/<id> 브랜치에 커밋, status=in_review
             ▼
   worker_claude_review.sh  ← 구현자와 분리된 새 세션, diff만 보고 판단
             │
      ┌──────┴───────┐
      ▼               ▼
   approve        changes_requested
      │               │
   main 병합      todo로 되돌림(+review_notes, retries+1)
```

## 사전 준비

1. `claude` CLI 설치 후 `claude login` (구독 로그인. API 키 사용 금지)
2. `gemini` CLI 설치 후 개인 구글 계정으로 로그인
3. `jq`, `git`, `flock`, `systemd` (대부분의 리눅스 배포판에 기본 포함)
4. 이 템플릿을 실제 작업 대상 프로젝트 저장소 **안에** 두거나, 스크립트들이 대상 프로젝트를
   가리키도록 경로를 맞추세요. (`scripts/lib/common.sh`의 `REPO_DIR` 계산 로직은 "이 템플릿이
   프로젝트 루트에 그대로 있다"고 가정합니다. 별도 프로젝트를 다루려면 `REPO_DIR`을
   `config/settings.env`에서 덮어쓰세요.)

## 설치

```bash
git clone <이 템플릿을 적용할 프로젝트 저장소>
cd <프로젝트>
# AITemplate 내용을 프로젝트 루트에 복사(스크립트, systemd, prompts, tasks, config, .gitignore 항목)
./install.sh
```

`install.sh`는 `systemd --user` 유닛을 설치하고 타이머를 활성화합니다.

```bash
systemctl --user status ai-orchestrator.timer      # 상태 확인
systemctl --user list-timers ai-orchestrator.timer # 다음 실행 시각
journalctl --user -u ai-orchestrator.service -f    # 실시간 로그
```

> systemd `--user` 서비스는 기본적으로 로그아웃하면 같이 꺼집니다. 로그인 세션 없이도
> 계속 돌리려면 `loginctl enable-linger $USER`를 실행해두세요.

## 작업 추가하기

```bash
# 복잡도를 Gemini가 자동으로 분류
./scripts/add_task.sh "네비게이션 메뉴에 다크모드 토글 버튼 추가"

# 복잡도를 직접 지정
./scripts/add_task.sh "결제 모듈 리팩터링 및 예외 처리 개선" complex
```

`tasks/queue.example.jsonl`에 예시가 있습니다. 큐 포맷:

```json
{"id": "task-...", "desc": "...", "complexity": "simple|complex",
 "status": "todo|in_progress|in_review|done|blocked",
 "assignee": null, "retries": 0, "review_notes": ""}
```

## 재시도/차단 정책

- 리뷰에서 `changes_requested`를 받으면 원래 구현자에게 재작업이 배정되고 `retries`가 1 증가합니다.
- `retries`가 `MAX_RETRIES`(기본 3)에 도달하면 `status`가 `blocked`로 바뀌고 더 이상 자동으로
  건드리지 않습니다. `review_notes`를 보고 사람이 직접 개입하세요.

## 커스터마이징 포인트

- **한도 감지 문구**: `scripts/lib/common.sh`의 `detect_limit_and_cooldown` 함수가 CLI 출력에서
  "usage limit / rate limit / resets at" 같은 문구를 정규식으로 찾습니다. Claude Code나 Gemini
  CLI가 실제로 내보내는 메시지가 바뀌면 이 정규식을 실제 출력에 맞게 수정하세요.
- **페르소나**: `prompts/*.md` 세 파일이 각각 구현자(Claude)/리뷰어(Claude)/대량작업자(Gemini)의
  태도를 정의합니다. 프로젝트 컨벤션에 맞게 자유롭게 고치세요.
- **라우팅 기준**: 지금은 `complexity` 태그 하나로만 나누지만, 파일 개수·예상 diff 크기 등
  다른 기준을 추가해도 됩니다.
- **1차 필터로 Gemini 활용**: Claude 쿼터를 더 아끼고 싶다면 `worker_claude_review.sh` 앞에
  Gemini로 "명백한 문법 오류/테스트 누락"만 먼저 거르는 1차 리뷰 단계를 추가하고, 그걸 통과한
  diff만 Claude 최종 리뷰로 보내는 2단계 구조로 확장할 수 있습니다.

## 주의사항

- `--dangerously-skip-permissions` 플래그로 CLI가 파일을 자유롭게 수정/커밋하게 되어 있습니다.
  신뢰할 수 있는 프로젝트에서만, 가능하면 별도 브랜치/샌드박스 환경에서 쓰세요.
- 무인 자동화가 이용약관상 문제되지 않는지(특히 다중 계정으로 한도를 우회하는 행위 등) 최신
  Anthropic/Google 이용약관을 확인하세요. 정상적인 "한도 대기 후 재개"는 통상 문제가 되지
  않지만, 판단은 사용자 본인 책임입니다.
- 이 템플릿은 뼈대일 뿐 프로덕션급 에러 처리를 전부 갖추고 있지 않습니다. 실제로 쓰기 전에
  안전한 테스트 저장소에서 몇 사이클 돌려보고 로그(`state/orchestrator.log`)를 확인하세요.
