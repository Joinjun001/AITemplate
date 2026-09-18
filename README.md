# AITemplate

컴퓨터가 켜져 있는 동안, **구독/무료 한도 안에서** Claude Code와 Gemini(기본값: Antigravity
CLI, `agy`)를 조합해 작업 큐를 자동으로 처리하는 셀프호스팅 오케스트레이션 템플릿입니다.
**Linux / macOS / Windows에서 같은 코드로 동작**하도록 순수 Python(표준 라이브러리만)으로
작성했고, OS별 스케줄러(systemd / launchd / 작업 스케줄러)만 자동으로 갈아 끼웁니다.

## 🚀 바로 시작하기 (입력할 명령어)

```bash
# 0) 최초 1회 — 설치 (OS를 자동 감지해서 알맞은 스케줄러에 orchestrator.py를 등록)
python install.py

# 1) 작업 하나만 추가하고 싶을 때 (백그라운드 스케줄러가 순서대로 처리)
python scripts/add_task.py "작업 설명"

# 2) 프로젝트 하나를 통째로 맡기고, 백그라운드로 알아서 진행시키고 싶을 때
python scripts/plan_project.py "프로젝트 설명"

# 3) 지금 터미널에서 "한 번 실행 → 완성될 때까지" 끝까지 지켜보고 싶을 때 (★ 가장 많이 씀)
python scripts/run_project.py "할일 관리 REST API 서버를 Flask + SQLite로 만들어줘. CRUD 엔드포인트, 입력 검증, pytest 테스트, README까지 포함해서."

# 중단했다가 이어서 진행하고 싶을 때
python scripts/run_project.py --resume
```

진행 상황은 `state/orchestrator.log`에서 실시간으로 볼 수 있습니다(`tail -f state/orchestrator.log`).

> ⚠️ **위 명령어는 반드시 `claude login`/Google 로그인으로 인증해 둔 실제 사용자 본인의
> 컴퓨터에서 직접 실행하세요.** `claude`/`agy`는 그 컴퓨터에 로그인된 구독(Claude Pro,
> Gemini Pro/Ultra)을 그대로 쓰기 때문에, 파일만 옮겨주는 원격 브리지나 다른 서버에서는
> 대신 실행해줄 수 없습니다.

- **Claude**: 복잡한 설계 판단이 필요한 구현 + 최종 코드 리뷰 (Claude Pro/Max 구독 토큰)
- **Gemini(agy)**: 토큰이 넉넉한 대량/단순 작업 처리 + 작업 난이도 자동 분류 (Gemini Pro/Ultra 구독 토큰)
- **plan_project.py / run_project.py**: 프로젝트 설명 하나를 던지면 Claude가 여러 작업으로
  쪼개서 큐에 통째로 등록 — 작업을 하나씩 손으로 넣을 필요 없이 프로젝트 전체를 맡길 수 있습니다
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

> 이 저장소는 실행 가능한 뼈대(스켈레톤)입니다. 실제 프로젝트 저장소 안에 그대로
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
OS 스케줄러 (예: 5분마다)                    run_project.py
  systemd timer(Linux)                     (터미널에서 직접 실행,
  launchd(macOS)                            같은 사이클을 끝날 때까지
  작업 스케줄러(Windows)                     이 프로세스 안에서 반복)
        │                                          │
        └───────────────────┬──────────────────────┘
                             ▼
                  scripts/orchestrator.py   -- 파일 락으로 중복 실행 방지
                             │
                    state/claude_until, state/gemini_until 로 쿨다운(한도) 확인
                             ▼
                  tasks/queue.jsonl (todo / in_progress / in_review / done / blocked)
                             │
                 ┌───────────┴─────────────┐
                 ▼                          ▼
       worker_gemini.py(agy)       worker_claude_impl.py
       (complexity=simple)         (complexity=complex)
                 │                          │
                 └────────────┬─────────────┘
                               ▼
                task/<id> 브랜치에 커밋, status=in_review
                               ▼
                worker_claude_review.py  ← 구현자와 분리된 새 세션, diff만 보고 판단
                               │
                        ┌──────┴───────┐
                        ▼               ▼
                     approve        changes_requested
                        │               │
                  BASE_BRANCH 병합   todo로 되돌림(+review_notes, retries+1)
                  (기본값 main)
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

**2. 스케줄러가 깨어남** — 5분 뒤(또는 다음 스케줄) `orchestrator.py`가 실행됩니다. 한 사이클은
리뷰 1건 + simple(Gemini) todo 1건 + complex(Claude) todo 1건, 이렇게 최대 세 가지 일을
순서대로 처리합니다(둘 다 있으면 같은 사이클에 같이 진행되어, 작업이 많이 쌓여 있을 때
훨씬 빨리 끝까지 진행됩니다):

```
[04:16:14] ===== orchestrator 사이클 시작 =====
[04:16:14] 리뷰 대기 작업 없음
[04:16:14] worker_gemini.py 실행: task-...b5b972              <- simple todo 하나
[04:16:14] Gemini 작업 완료, 리뷰 대기로 전환: task-...b5b972
[04:16:14] worker_claude_impl.py 실행: task-...0046bb          <- complex todo 하나
[04:16:15] Claude 구현 완료, 리뷰 대기로 전환: task-...0046bb
[04:16:15] ===== orchestrator 사이클 종료 =====
```

내부적으로는: `git checkout -B task/<id> <BASE_BRANCH>` → 페르소나 프롬프트로 `claude -p "..."`
(simple이면 `agy -p "..."`) 실행 → 파일이 바뀌었으면 `git commit` → 큐 상태를
`in_review`로 변경. 만약 이 시점에 Claude/Gemini 사용량 한도 메시지가 감지되면, 커밋 없이
`todo`로 되돌리고 `state/claude_until`(또는 `gemini_until`)에 리셋 예상 시각을 적어둔 뒤
조용히 종료합니다 — 다음 사이클들은 그 시각이 지날 때까지 이 작업을 계속 건너뜁니다.

**3. 다음 사이클: 리뷰** — `in_review` 상태인 작업을 발견하면, 구현자와 완전히 분리된 새
`claude -p` 세션이 `git diff <BASE_BRANCH>..task/<id>`만 보고 판단합니다:

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

**5. 완료** — 승인되면 `task/<id>` 브랜치가 `--no-ff`로 기준 브랜치(`BASE_BRANCH`, 기본 `main`)에
병합되고, 브랜치는 삭제되고, 작업은 `status: done`으로 남습니다. `git log --oneline --graph`로
보면 구현 커밋과 병합 커밋이 그대로 히스토리에 남아서, 나중에 "이 변경 누가/왜 했는지"를 리뷰
코멘트와 함께 추적할 수 있습니다.

**만약 병합 중 충돌이 나면**(같은 사이클에 여러 작업을 진행하다 보면, 다른 작업이 먼저
병합되면서 기준 브랜치가 앞서가 있어 겹치는 파일을 건드린 경우 충돌이 날 수 있습니다) 자동으로
`git merge --abort`로 정리하고, "기준 브랜치와 충돌났으니 최신 기준으로 다시 구현해달라"는
review_notes와 함께 `todo`로 돌려보냅니다. 사람이 개입할 필요 없이 다음 번 구현 시도에서
최신 기준 브랜치를 기준으로 다시 브랜치를 파기 때문에 대부분 그 다음엔 깨끗하게 병합됩니다.

**한 사이클에 일어나는 일 정리**: 리뷰 대기 있으면 리뷰 1건 → simple todo 있으면 구현 1건 →
complex todo 있으면 구현 1건, 이렇게 최대 3번의 CLI 호출을 하고 끝냅니다. 확인하고 싶으면
`state/orchestrator.log`를 tail 하면서 지켜보시면 됩니다.

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
`orchestrator.py` 실행 중 `task/<id>` 브랜치와 기준 브랜치를 오가며 이 파일을 갱신하는데, git이
추적하는 파일이면 브랜치마다 내용이 달라질 때 `git checkout`이 막혀버리기 때문입니다
(직접 겪은 문제라 템플릿에 미리 반영해뒀습니다). 예시/참고용인 `tasks/queue.example.jsonl`만
커밋됩니다. 큐 포맷(JSONL, 한 줄에 작업 하나):

```json
{"id": "task-...", "desc": "...", "complexity": "simple|complex",
 "status": "todo|in_progress|in_review|done|blocked",
 "assignee": null, "retries": 0, "review_notes": ""}
```

## 프로젝트 통째로 맡기기 (자동 작업 분해)

작업을 하나씩 `add_task.py`로 넣는 대신, 프로젝트 설명 하나를 던지면 Claude가 알아서
여러 개의 작업으로 쪼개서 큐에 한 번에 넣어주는 스크립트가 두 개 있습니다. 프로젝트를 어떻게
분해하는지는 둘 다 동일하고(`prompts/planner_persona.md` 페르소나로 Claude를 한 번 불러
JSON 배열 `[{"desc": "...", "complexity": "simple|complex"}, ...]`을 받음), **그 다음에
누가 처리하느냐**만 다릅니다.

|  | `plan_project.py` | `run_project.py` |
|---|---|---|
| 하는 일 | 작업을 쪼개서 큐에 넣고 **바로 종료** | 큐에 넣은 뒤 **완료될 때까지 이 터미널에서 계속 진행** |
| 실제 처리 주체 | 이후 백그라운드 스케줄러(`install.py`로 등록, 기본 5분 간격) | 이 명령을 실행 중인 프로세스 자신 |
| 언제 쓰나 | 컴퓨터를 며칠씩 켜두고 여러 프로젝트를 틈틈이 처리하고 싶을 때 | 지금 프로젝트 하나를 몰아서 끝까지 보고 싶을 때 (★ 보통 이걸 씁니다) |

```bash
# 큐에 등록만 하고 끝 (스케줄러가 알아서 처리)
python scripts/plan_project.py "프로젝트 설명"

# 등록 + 끝날 때까지 이 터미널에서 계속 진행 (Ctrl+C로 중단, --resume으로 재개)
python scripts/run_project.py "프로젝트 설명"

# 스펙이 길면 파일로 (둘 다 지원)
python scripts/plan_project.py --file project_spec.txt
```

**이 호출(계획 단계)은 파일을 읽거나 쓰지 않는 순수 텍스트 추론이라
`--dangerously-skip-permissions`를 주지 않습니다** — 계획 단계에서는 저장소를 건드릴
권한 자체를 안 주는 게 안전하다고 판단했습니다.

몇 가지 참고할 점:
- 배열 순서 = 처리 순서입니다. 플래너는 "뒤 작업이 앞 작업 결과물에 의존하면 순서대로
  넣으라"는 지시를 받지만, 완벽하지 않을 수 있으니 결과를 한 번 훑어보고 이상하면
  `tasks/queue.jsonl`을 직접 편집해서 순서나 내용을 고쳐도 됩니다.
- 사용량 한도에 걸리면 평소처럼 조용히 쉬었다가 자동으로 이어집니다. 큰 프로젝트를
  통째로 맡기면 그 하루 한도를 거의 다 쓰게 될 수 있다는 뜻이기도 합니다.
  `run_project.py`는 쿨다운이 풀리는 시각까지 계산해서 그때 자동으로 다시 시도하므로,
  대형 프로젝트라면 5시간짜리 Claude 한도를 몇 번 거쳐가며 몇 시간 동안 터미널이 켜져
  있을 수도 있습니다.
- 완료된 작업들은 각각 별도 커밋 + 병합 커밋으로 남기 때문에, `git log --oneline`으로
  전체 프로젝트가 어떤 순서로 만들어졌는지 그대로 다시 볼 수 있습니다.
- `run_project.py`는 백그라운드 스케줄러가 이미 설치되어 있어도 동시에 실행해서 상관없습니다
  (같은 파일 락을 공유해서 서로 겹치지 않게 비켜갑니다). 다만 로그가 섞여 보기 불편하니
  실제로는 하나만 켜두는 걸 권장합니다.
- `run_project.py`는 끝나면 완료/차단(blocked) 건수를 요약해서 보여주고, `blocked`가 있으면
  어떤 작업이 왜 막혔는지(`review_notes`)까지 함께 출력합니다.

## 연습 브랜치로 안전하게 실습해보기

`main`을 바로 쓰기 전에, 별도 브랜치 안에서만 orchestrator가 작업하도록 격리해서
연습해볼 수 있습니다. `BASE_BRANCH` 설정 덕분에 실제 히스토리(`main`)는 전혀 건드리지
않습니다.

```bash
# 1) main에서 연습용 브랜치를 하나 판다
git checkout -b practice/todo-api main

# 2) config/settings.json 에서 BASE_BRANCH를 그 브랜치로 지정
#    (config/settings.json은 .gitignore에 있어서 커밋되지 않습니다)
echo '{"BASE_BRANCH": "practice/todo-api"}' > config/settings.json

# 3) 위 "바로 시작하기"의 run_project.py 명령을 그대로 실행
python scripts/run_project.py "할일 관리 REST API 서버를 Flask + SQLite로 만들어줘. CRUD 엔드포인트, 입력 검증, pytest 테스트, README까지 포함해서."
```

이렇게 하면 `task/<id>` 브랜치들은 전부 `practice/todo-api`에서 갈라져 나와
`practice/todo-api`로 다시 병합되고, `main`은 그대로 남습니다. 다 끝난 뒤 결과가
마음에 들면 `git checkout main && git merge --no-ff practice/todo-api`로 가져오고,
마음에 안 들면 그냥 `git branch -D practice/todo-api`로 지우면 됩니다(단, `queue.jsonl`은
브랜치와 무관하게 파일시스템에 그대로 남는 상태이므로, 연습이 끝나면
`tasks/queue.jsonl`을 비우고 `config/settings.json`의 `BASE_BRANCH`를 다시 `"main"`으로
되돌리는 것을 잊지 마세요).

## 재시도/차단 정책

- 리뷰에서 `changes_requested`를 받으면 원래 구현자에게 재작업이 배정되고 `retries`가 1 증가합니다.
- `retries`가 `MAX_RETRIES`(기본 3)에 도달하면 `status`가 `blocked`로 바뀌고 더 이상 자동으로
  건드리지 않습니다. `review_notes`를 보고 사람이 직접 개입하세요.

## 설정 조정

`config/settings.json.example`을 `config/settings.json`으로 복사해서 값을 바꾸세요
(이 파일은 `.gitignore`에 포함되어 커밋되지 않습니다).

| 키 | 기본값 | 설명 |
|---|---|---|
| `MAX_RETRIES` | `3` | 재시도 상한 |
| `COOLDOWN_MIN_CLAUDE` | `300` | 리밋 메시지는 감지했는데 정확한 리셋 시각을 못 읽었을 때 기본 대기(분). Claude Code는 롤링 5시간 한도라 기본값 300분 |
| `COOLDOWN_MIN_GEMINI` | `60` | 위와 동일하되 Gemini용. 보통 자정 기준 일일 한도라 짧게 잡음 |
| `CYCLE_INTERVAL_MIN` | `5` | 스케줄러가 orchestrator를 부르는 주기(분). `install.py`를 다시 실행하면 반영됨 |
| `GEMINI_CLI_CMD` | `"agy"` | Gemini 역할을 실행할 실제 명령어 이름. 독립 `gemini` CLI로 바꾸려면 `"gemini"`로 설정. 단, 독립 `gemini` CLI는 `--dangerously-skip-permissions` 플래그를 지원하지 않을 수 있으니, 바꾼 뒤 `scripts/common.py`의 `gemini_cli_argv`에서 그 플래그 추가 부분을 빼야 할 수도 있음 |
| `GEMINI_MODEL` | `""` | `agy --model`로 넘길 모델 이름(예: `"Gemini 3.1 Pro"`). 빈 문자열이면 계정 기본 모델. **Claude 모델 이름을 넣지 말 것** — 위 경고 참고 |
| `BASE_BRANCH` | `"main"` | 작업 브랜치의 기준이자 병합 대상 브랜치. 연습/테스트를 할 때는 `"practice/todo-api"`처럼 별도 브랜치로 바꿔서 `main`을 건드리지 않고 격리해서 돌려볼 수 있음(위 "연습 브랜치로 안전하게 실습해보기" 참고) |
| `RUN_LOOP_POLL_SEC` | `20` | `run_project.py`가 할 일이 없을 때(쿨다운 등) 다음 시도까지 재우는 최소 시간(초). 실제로는 쿨다운이 끝나는 시각까지 알아서 더 길게 잠 |

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
  안전한 테스트 저장소(위 "연습 브랜치로 안전하게 실습해보기" 참고)에서 몇 사이클 돌려보고
  로그(`state/orchestrator.log`)를 확인하세요.
