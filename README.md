# AITemplate

컴퓨터가 켜져 있는 동안, **구독/무료 한도 안에서** Claude Code와 Gemini(기본값: Antigravity
CLI, `agy`)를 조합해 작업 큐를 자동으로 처리하는 셀프호스팅 오케스트레이션 템플릿입니다.
**Linux / macOS / Windows에서 같은 코드로 동작**하도록 순수 Python(표준 라이브러리만)으로
작성했고, OS별 스케줄러(systemd / launchd / 작업 스케줄러)만 자동으로 갈아 끼웁니다.

- **Claude**: 복잡한 설계 판단이 필요한 구현 + 최종 코드 리뷰 (Claude Pro/Max 구독 토큰)
- **Gemini(agy)**: 토큰이 넉넉한 대량/단순 작업 처리 + 작업 난이도 자동 분류 (Gemini Pro/Ultra 구독 토큰)
- **OS 스케줄러**: 사용량 한도(토큰) 소진으로 멈춘 작업을, 한도가 풀리는 대로 자동 재개

> **왜 agy인가**: [Antigravity CLI](https://antigravity.google/download#antigravity-cli)(명령어
> 이름 `agy`)는 구글 계정으로 로그인해서 Gemini Pro/Ultra 구독 토큰을 그대로 쓰는 CLI입니다.
> `-p`, `--dangerously-skip-permissions` 등 Claude Code CLI와 거의 같은 플래그를 지원해서
> 자동화 스크립트를 거의 그대로 재사용할 수 있습니다. 실제 실행 파일 이름은
> `config/settings.json`의 `GEMINI_CLI_CMD`로 바꿀 수 있으니, 독립 `gemini` CLI를 쓰고
> 싶다면 그쪽으로 바꾸면 됩니다.
>
> ⚠️ **agy로 Claude 모델을 부르지 마세요**: `agy --model="Claude ..."`도 가능하지만, 이건
> Anthropic claude.ai의 Claude Pro 구독이 아니라 **Google 플랜에 번들된 별도의 Claude 접근권**을
> 씁니다. 이 템플릿에서 "Claude 역할"은 반드시 실제 `claude` CLI(Claude Code, `claude login`)로만
> 실행되어, 사용자님의 진짜 Claude Pro 구독 5시간 한도를 쓰도록 되어 있습니다.

> 이 저장소는 실행 가능한 뼈대(스킬레톤)입니다. 실제 프로젝트 저장소 안에 그대로
> 복사해 넣거나, 스크립트들이 대상 프로젝트를 가리키도록 경로를 맞춰 쓰세요.

## 왜 이런 구조인가 (요약)

- Claude Code를 **구독(Pro/Max) 로그인**으로 쓰면 월정액 안에서 자동화해도 추가 과금이 없습니다.
  대신 5시간 롤링 한도에 걸리면 완전히 멈춥니다 — 이걸 OS 스케줄러가 "한도 풀릴 때까지
  기다렸다가 자동 재개"로 해결합니다.
- Gemini(agy)는 구글 계정 로그인 기준 Google AI 플랜(무료/Pro/Ultra) 구독 한도를 그대로
  씁니다. 컨텍스트가 크고 판단이 단순한 작업(반복 수정, 대량 파일 처리 등)을 여기로 보내면
  Claude 쿼터를 아낄 수 있습니다.
- **비용 폭탄을 막으려면**: `ANTHROPIC_API_KEY` 환경변수를 이 스크립트를 실행하는 프로세스/
  systemd 유닛/launchd plist/작업 스케줄러 어디에도 넣지 마세요. 넣는 순간 종량제 API 과금으로
  전환됩니다. Extra Usage(종량제 오버플로우)도 켜지 마세요. `claude`/`agy` 모두 API 키가 아니라
  구독 로그인(`claude login` / agy의 구글 로그인)으로 인증된 상태로만 실행되어야 합니다.
- 리뷰는 **구현자와 완전히 분리된 새 세션**에서 diff만 보고 판단합니다(같은 대화를 이어가면
  자기가 짠 코드를 관대하게 봐주는 확증편향이 생기기 쉽습니다).

## 아키텍처

```
OS 스케줄러 (예: 5분마다)
  systemd timer(Linux) / launchd(macOS) / 작업 스케줄러(Windows)
        │
        ▼
  scripts/orchestrator.py   -- 파일 락으로 중복 실행 방지
        │
        ├─ state/claude_until, state/gemini_until 로 쿨다운(한도) 확인
        │
        ▼
  tasks/queue.jsonl (todo / in_progress / in_review / done / blocked)
        │
   ┌────┴─────────────────┐
   ▼                       ▼
worker_gemini.py(agy)    worker_claude_impl.py
(complexity=simple)      (complexity=complex)
   │                       │
   └───────────┬───────────┘
               ▼
   task/<id> 브랜치에 커밋, status=in_review
               ▼
   worker_claude_review.py  ← 구현자와 분리된 새 세션, diff만 보고 판단
               │
        ┌──────┴───────┐
        ▼               ▼
     approve        changes_requested
        │               │
     main 병합      todo로 되돌림(+review_notes, retries+1)
```

## 사전 준비 (OS 공통)

1. Python 3.9+ (대부분 macOS/Linux에 기본 설치, Windows는 [python.org](https://python.org)
   또는 `winget install Python.Python.3` / `scoop install python`)
2. `claude` CLI(Claude Code) 설치 후 `claude login` (구독 로그인. **API 키 사용 금지**)
3. [Antigravity CLI](https://antigravity.google/download#antigravity-cli) 설치 후 `agy` 실행해서
   구글 계정으로 로그인 (Gemini Pro/Ultra 구독 계정). 독립 `gemini` CLI를 쓰고 싶다면 그걸 설치하고
   `config/settings.json`의 `GEMINI_CLI_CMD`를 `"gemini"`로 바꾸세요.
4. `git`
5. 이 템플릿을 실제 작업 대상 프로젝트 저장소 **안에** 두거나, 스크립트들이 대상 프로젝트를
   가리키도록 경로를 맞추세요. (`scripts/common.py`의 `REPO_DIR`은 "이 템플릿이 프로젝트
   루트에 그대로 있다"고 가정하고 `scripts/`의 부모 디렉터리로 계산합니다.)

## 설치

```bash
git clone <이 템플릿을 적용할 프로젝트 저장소>
cd <프로젝트>
# AITemplate 내용을 프로젝트 루트에 복사(scripts/, prompts/, tasks/, config/, install.py, .gitignore 항목)
python install.py
```

`install.py`가 현재 OS(Linux/macOS/Windows)를 자동 감지해서 알맞은 스케줄러에
`orchestrator.py`를 등록합니다.

| OS | 사용하는 스케줄러 | 상태 확인 | 로그 |
|---|---|---|---|
| Linux | `systemd --user` timer | `systemctl --user status ai-orchestrator.timer` | `journalctl --user -u ai-orchestrator.service -f` |
| macOS | `launchd` (LaunchAgent) | `launchctl list \| grep aitemplate` | `state/launchd.out.log` |
| Windows | 작업 스케줄러(`schtasks`) | `schtasks /Query /TN AITemplateOrchestrator /V /FO LIST` | `state/orchestrator.log` |

> **Linux/WSL 참고**: WSL2에서 `systemctl`이 없다고 나오면 `/etc/wsl.conf`에
> `[boot]\nsystemd=true`를 추가하고 `wsl --shutdown` 후 다시 켜서 재시도하세요.
>
> **Linux 참고**: `systemd --user` 서비스는 로그아웃하면 같이 꺼집니다. 로그인 세션 없이도
> 계속 돌리려면 `loginctl enable-linger $USER`를 실행해두세요.
>
> **Windows 참고**: 일반 사용자 권한에서 `schtasks` 등록이 실패하면 관리자 권한 터미널로
> 다시 시도하거나, 출력되는 안내대로 작업 스케줄러 GUI에서 수동 등록하세요.

## 실행하면 어떻게 진행되나요 (실행 흐름)

설치만 해두면 그 다음부터는 사람이 손댈 일 없이 아래 흐름이 반복됩니다. 실제로 스텁으로
돌려서 확인한 로그를 그대로 예로 듭니다.

**0. 준비** — `python install.py`가 OS를 감지해서 스케줄러(systemd/launchd/작업 스케줄러)에
`orchestrator.py`를 등록해둡니다. 이후로는 사람이 다시 실행할 필요 없이, 컴퓨터가 켜져 있는 한
5분마다(기본값, `CYCLE_INTERVAL_MIN`으로 조절) 자동으로 깨어납니다.

**1. 작업 등록** — `python scripts/add_task.py "결제 예외 처리 추가"`를 실행하면
`tasks/queue.jsonl`에 `status: "todo"`인 항목이 한 줄 추가됩니다. complexity를 안 정했으면
그 자리에서 `agy`를 한 번 불러 simple/complex를 분류합니다.

**2. 스케줄러가 깨어남** — 5분 뒤(또는 다음 스케줄) `orchestrator.py`가 실행됩니다. 매 사이클은
이렇게 흘러갑니다:

```
[04:16:14] ===== orchestrator 사이클 시작 =====
[04:16:14] 리뷰 대기 작업 없음                              <- in_review 작업부터 먼저 확인
[04:16:14] Claude 구현 워커 실행: task-20260919041614        <- todo 작업을 하나 꺼내서 라우팅
[04:16:15] Claude 구현 완료, 리뷰 대기로 전환: task-...       <- 커밋 후 status: in_review
[04:16:15] ===== orchestrator 사이클 종료 =====
```

내부적으로는: `git checkout -B task/<id> main` → 페르소나 프롬프트로 `claude -p "..."`
(또는 simple이면 `agy -p "..."`) 실행 → 파일이 바뀌었으면 `git commit` → 큐 상태를
`in_review`로 변경. 만약 이 시점에 Claude/Gemini 사용량 한도 메시지가 감지되면, 커밋 없이
`todo`로 되돌리고 `state/claude_until`(또는 `gemini_until`)에 리셋 예상 시각을 적어둔 뒤
조용히 종료합니다 — 다음 사이클들은 그 시각이 지날 때까지 이 작업을 계속 건너뜁니다.

**3. 다음 사이클: 리뷰** — `in_review` 상태인 작업을 발견하면, 구현자와 완전히 분리된 새
`claude -p` 세션이 `git diff main..task/<id>`만 보고 판단합니다:

```
[04:16:20] 리뷰 실행: task-20260919041614
[04:16:20] 리뷰 승인 -> main 병합 완료: task-20260919041614   <- git merge --no-ff, 브랜치 삭제, status: done
```

반려된 경우는 이렇게 됩니다:

```
[04:16:15] 리뷰 반려 -> 재작업 큐로: task-20260919041614
                         <- status: todo로 되돌리고, review_notes에 리뷰 코멘트 기록, retries: 1
```

**4. 재작업** — 같은 사이클 안에서(또는 다음 사이클에서) 이 작업이 다시 `todo`로 잡혀서 같은
구현자에게 배정됩니다. 이번엔 프롬프트에 이전 리뷰 코멘트("에러 처리 누락", "테스트 추가 필요"
같은)가 그대로 포함되어 들어갑니다. 이 승인/반려 루프는 `retries`가 `MAX_RETRIES`(기본 3)에
도달할 때까지 반복되고, 그래도 안 되면 `status: blocked`로 멈춰서 더 이상 자동으로 건드리지
않습니다 — 이때는 `tasks/queue.jsonl`의 `review_notes`를 열어서 사람이 직접 봐야 합니다.

**5. 완료** — 승인되면 `task/<id>` 브랜치가 `--no-ff`로 `main`에 병합되고, 브랜치는 삭제되고,
작업은 `status: done`으로 남습니다. `git log --oneline --graph`로 보면 구현 커밋과 병합
커밋이 그대로 히스토리에 남아서, 나중에 "이 변경 누가/왜 했는지"를 리뷰 코멘트와 함께
추적할 수 있습니다.

**한 사이클에 일어나는 일 정리**: (리뷰 대기 있으면 리뷰 1건) → (todo 있으면 구현 1건) 순서로
최대 2번의 CLI 호출만 하고 끝냅니다. 작업이 여러 개 쌓여 있어도 사이클당 하나씩만 처리하기
때문에, 확인하고 싶으면 `state/orchestrator.log`를 tail 하면서 지켜보시면 됩니다.

```bash
tail -f state/orchestrator.log
```

## 작업 추가하기

```bash
# 복잡도를 Gemini가 자동으로 분류
python scripts/add_task.py "네비게이션 메뉴에 다크모드 토글 버튼 추가"

# 복잡도를 직접 지정
python scripts/add_task.py "결제 모듈 리팩터링 및 예외 처리 개선" complex
```

`tasks/queue.jsonl`은 의도적으로 `.gitignore`에 들어 있어 버전관리되지 않습니다. 워커들이
`orchestrator.py` 실행 중 `task/<id>` 브랜치와 `main`을 오가며 이 파일을 갱신하는데, git이
추적하는 파일이면 브랜치마다 내용이 달라질 때 `git checkout`이 막혀버리기 때문입니다
(직접 겪은 문제라 템플릿에 미리 반영해뒀습니다). 예시/참고용인 `tasks/queue.example.jsonl`만
커밋됩니다. 큐 포맷(JSONL, 한 줄에 작업 하나):

```json
{"id": "task-...", "desc": "...", "complexity": "simple|complex",
 "status": "todo|in_progress|in_review|done|blocked",
 "assignee": null, "retries": 0, "review_notes": ""}
```

## 재시도/차단 정책

- 리뷰에서 `changes_requested`를 받으면 원래 구현자에게 재작업이 배정되고 `retries`가 1 증가합니다.
- `retries`가 `MAX_RETRIES`(기본 3)에 도달하면 `status`가 `blocked`로 바뀌고 더 이상 자동으로
  건드리지 않습니다. `review_notes`를 보고 사람이 직접 개입하세요.

## 설정 조정

`config/settings.json.example`을 `config/settings.json`으로 복사해서 값을 바꾸세요
(이 파일은 `.gitignore`에 포함되어 커밋되지 않습니다).

- `MAX_RETRIES`: 재시도 상한
- `COOLDOWN_MIN_CLAUDE`: 리밋 메시지는 감지했는데 정확한 리셋 시각을 못 읽었을 때 기본 대기(분).
  Claude Code는 롤링 5시간 한도라 기본값 300분.
- `COOLDOWN_MIN_GEMINI`: 위와 동일하되 Gemini용. 보통 자정 기준 일일 한도라 짧게 잡았습니다.
- `CYCLE_INTERVAL_MIN`: 스케줄러가 orchestrator를 부르는 주기(분). `install.py`를 다시 실행하면
  반영됩니다.
- `GEMINI_CLI_CMD`: Gemini 역할을 실행할 실제 명령어 이름. 기본값 `"agy"`(Antigravity CLI).
  독립 `gemini` CLI로 바꾸려면 `"gemini"`로 설정하세요. 단, 독립 `gemini` CLI는
  `--dangerously-skip-permissions` 플래그를 지원하지 않을 수 있으니, 바꾼 뒤
  `scripts/common.py`의 `gemini_cli_argv`에서 그 플래그 추가 부분을 빼야 할 수도 있습니다.
- `GEMINI_MODEL`: `agy --model`로 넘길 모델 이름(예: `"Gemini 3.1 Pro"`). 빈 문자열이면
  계정 기본 모델을 씁니다. **Claude 모델 이름을 넣지 마세요** — 위 경고 참고.

## 커스터마이징 포인트

- **한도 감지 문구**: `scripts/common.py`의 `detect_limit_and_set_cooldown` 함수(`LIMIT_PATTERN`)가
  CLI 출력에서 "usage limit / rate limit / resets at" 같은 문구를 정규식으로 찾습니다. Claude
  Code나 agy(Antigravity CLI)가 실제로 내보내는 메시지가 바뀌면 이 정규식을 실제 출력
  (`state/orchestrator.log`에 일부가 남습니다)에 맞게 수정하세요.
- **페르소나**: `prompts/*.md` 세 파일이 각각 구현자(Claude)/리뷰어(Claude)/대량작업자(Gemini)의
  태도를 정의합니다. 프로젝트 컨벤션에 맞게 자유롭게 고치세요.
- **라우팅 기준**: 지금은 `complexity` 태그 하나로만 나누지만, 파일 개수·예상 diff 크기 등
  다른 기준을 추가해도 됩니다.
- **1차 필터로 Gemini 활용**: Claude 쿼터를 더 아끼고 싶다면 `worker_claude_review.py` 앞에
  Gemini로 "명백한 문법 오류/테스트 누락"만 먼저 거르는 1차 리뷰 단계를 추가하고, 그걸 통과한
  diff만 Claude 최종 리뷰로 보내는 2단계 구조로 확장할 수 있습니다.

## 주의사항

- `--dangerously-skip-permissions` 플래그로 CLI가 파일을 자유롭게 수정/커밋하게 되어 있습니다.
  신뢰할 수 있는 프로젝트에서만, 가능하면 별도 브랜치/샌드박스 환경에서 쓰세요.
- 무인 자동화가 이용약관상 문제되지 않는지(특히 다중 계정으로 한도를 우회하는 행위 등) 최신
  Anthropic/Google 이용약관을 확인하세요. 정상적인 "한도 대기 후 재개"는 통상 문제가 되지
  않지만, 판단은 사용자 본인 책임입니다.
- Windows에서 npm/설치 스크립트로 깐 CLI(`claude.cmd`, `agy.exe` 등)를 못 찾는 경우, PATH에
  해당 설치 경로가 등록돼 있는지 확인하세요(`common.py`가 `shutil.which`로 찾습니다).
- 이 템플릿은 뼈대일 뿐 프로덕션급 에러 처리를 전부 갖추고 있지 않습니다. 실제로 쓰기 전에
  안전한 테스트 저장소에서 몇 사이클 돌려보고 로그(`state/orchestrator.log`)를 확인하세요.
