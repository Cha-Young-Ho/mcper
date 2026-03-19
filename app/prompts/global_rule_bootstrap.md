# [CRITICAL ACTION REQUIRED: APP_NAME MISSING]

현재 프로젝트의 룰을 로드하려면 **`app_name`** 파라미터가 반드시 필요합니다.  
**절대 app_name을 임의로 추측하거나 지어내지 마십시오.** 아래 절차를 정확히 따르세요.

---

## [필수] 룰 버전 점검 (`check_rule_versions`)

- MCP 도구 **`check_rule_versions`** 가 있다. 이 툴은 **서버 DB의 최신 룰 버전**을 **정수**(`1`, `2`, `3`, …)로, **global · repository(매칭된 패턴) · app** 별로 JSON에 담아 돌려준다.
- 로컬에 저장한 규칙 파일 상단 `<!-- rule_meta: … -->` 안의 **`global_served`**, **`repo_served`**, **`app_served`** 등과 **각각 비교**한다.
- **어느 하나라도 서버가 준 최신 버전 정수와 다르면**, 추측으로 덮어쓰지 말고 **`get_global_rule`** 을 **다시 호출**해 받은 **최신 본문으로 로컬 규칙 파일을 수정·저장**한다.

---

## [필수] 사용자가 "룰 받아와 / 조회 / 동기화" 라고 한 경우

- 사용자가 **「프로젝트 룰 받아와」「룰 조회해」「MCP 룰 가져와」** 등 **유사 표현**으로 요청하면, `get_global_rule` 결과를 **채팅에만 보여 주지 말고** `app_name` 확보 후 **2차 응답 전체를 사용 중 IDE 형식으로 디스크에 저장**합니다. (**명시적으로 저장 생략**을 말한 경우만 예외.)

---

## `app_name`이란 무엇인가 (중요)

- **설정 파일에 적힌 앱 식별자 한 덩어리**입니다. (예: `your_app_name`)
- **브랜치명·`/master`·슬래시 조합을 붙이지 않습니다.** `your_app_name/master` 같은 값으로 호출하지 마십시오. **`your_app_name`만** `get_global_rule(app_name="your_app_name")` 형태로 넘깁니다.
- 프로젝트 예시: `config.dev.ini` 등에 `[Global]` 섹션과 `app_name = "your_app_name"` 가 있으면, 인자는 **`your_app_name`** 입니다.

---

## [단계 1] 파일 검색

- 프로젝트 **루트 디렉터리**에서 **`config.dev.ini`** 또는 **`config.ini`** 파일을 읽으십시오.
- (프로젝트 규약에 따라) 보통 **`[Global]`** 등 섹션 아래 **`app_name`** 키의 **값만** 가져옵니다. 따옴표는 제거한 순수 식별자만 사용합니다.
- 값을 찾았다면 즉시 **`get_global_rule(app_name="찾은값")`** 을 재호출하십시오. (**슬래시나 접미사 없이**)

---

## [단계 2] 사용자 질의 (파일이 없거나 값을 못 찾은 경우)

- **추가로 다른 파일을 검색하지 마십시오.**
- 즉시 작업을 멈추고 **사용자에게 정확히** 다음과 같이 질문하십시오:

  **"작업 중인 앱 식별자(app_name)가 무엇인가요? 설정 파일의 `app_name`과 동일하게만 알려주세요. (예: `your_app_name` — 브랜치나 `/master`는 붙이지 않습니다.)"**

- 사용자가 답변하면 **INI에 쓰인 것과 같은 식별자만** 추려 **`get_global_rule(app_name="...")`** 로 재호출하십시오. 답에 `something/master` 형태가 섞여 있으면 **`/` 앞의 앱 식별자만** 사용하십시오.

---

## 금지 사항

- 폴더 이름·이전 대화·브랜치 이름 등으로 **app_name을 추측하지 마십시오.**
- **`app_name`에 `/master` 등을 붙여 호출하지 마십시오.** (팀 컨벤션상 앱 식별자는 INI 값 하나입니다.)
- [단계 1]에서 두 파일을 찾지 못했으면 **다른 ini/json/yaml 파일을 더 찾지 말고** [단계 2]로 넘어가십시오.

---

## [단계 3] 최종 룰을 **사용 중인 에이전트/IDE에 맞는 형식으로** 저장 (`app_name`으로 재호출 **한 뒤에만**)

- **MCP는 마크다운만 제공**합니다. **저장 경로·파일 포맷은 Cursor / Claude / Antigravity / Gemini 등 실제 환경**에 맞춥니다.
- `get_global_rule(app_name="확정값")` **2차 응답**을 **Git 저장소 루트** 기준으로 로컬에 씁니다. (읽기만 하고 끝내지 마십시오.)
  - 서브폴더만 열려 있으면 `git rev-parse --show-toplevel` 로 루트를 잡습니다.  
  - 멀티 루트면 `app_name` 이 나온 저장소 루트.  
  - MCP가 Docker면 **호스트 클론 경로**에 씁니다 (컨테이너 안 X).
- **세부 절차**는 2차 응답 말미 **`[CRITICAL — 사용 중인 에이전트/IDE에 맞게 로컬에 규칙 반영]`** 절을 따르십시오.
- **1단계(인자 없이 호출)로 받은 이 부트스트랩은 저장하지 마십시오.**

---

## [참고] `app_name` 확보 후: Global + Repository + App (3단)

- `get_global_rule(app_name="…", origin_url="…")` 로 **재호출**하는 것을 권장한다. **`origin_url`** 은 에이전트가 **`git remote -v`** 로 얻은 **origin 의 fetch URL** (`git@…` 또는 `https://…`).
- 응답에 **Global rule**(최신) + **Repository rule**(위 URL 과 DB 패턴 매칭) + **App rule**(`app_name` 스트림)이 순서로 포함될 수 있다.
- MCP 서버가 Git 을 못 읽는 환경(Docker 등)에서도 **`origin_url` 만 있으면** Repository 룰 매칭이 된다.
- 추가 확인은 **`git status`** 등. 불확실하면 **사용자에게** 저장소 루트·브랜치를 질문한다.

---
*다음: app_name을 확보한 뒤 `get_global_rule(app_name="your_app_name", origin_url=…)` 로 다시 호출하고, Cursor 는 **`.cursor/rules/mcp-rules.mdc`** 등 응답 말미 지시에 따라 저장하세요.*
