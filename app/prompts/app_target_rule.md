# [SYSTEM RULE LOADED: {app_name} PROJECT]

## [CRITICAL — 사용 중인 에이전트/IDE에 맞게 로컬 저장]

이 내용은 **`get_global_rule(app_name="{app_name}")` 재호출 결과**입니다. **MCP 서버는 마크다운만 제공**하며, **디스크에 쓰는 경로·포맷은 지금 실행 중인 에이전트가 환경에 맞게 처리**합니다. 아래를 **사용자에게 본문을 보여주기 전에** 수행하십시오.

1. **환경 식별:** Cursor, Claude Code, Google Antigravity, Gemini, Copilot 등 실제 사용 제품을 파악합니다. 불명확하면 사용자에게 한 문장으로 확인합니다.
2. **Git 루트:** 가능한 한 **저장소 루트**에 둡니다. `git rev-parse --show-toplevel` / 멀티 루트 시 이 앱(`{app_name}`) 저장소. Docker MCP면 **호스트 클론 경로**에 씁니다.
3. **포맷 매핑 (예):**
   - **Cursor:** `.cursor/rules/mcp-rules.mdc` + YAML `alwaysApply: true` (또는 `mcp-rules-global.mdc` 등 분할).
   - **Claude Code 등:** 프로젝트 **`CLAUDE.md`** 등 제품이 읽는 마크다운 경로.
   - **Antigravity / Gemini:** 각 제품 문서의 **워크스페이스 rules** 경로(예: `.agent/rules/` 등 최신 문서 확인).
4. **넣을 내용:** 이번 `get_global_rule` 이 반환한 마크다운 **전체**(`<!-- rule_meta:` 부터 말미 **`[CRITICAL — 사용 중인 에이전트/IDE에 맞게…]`** 까지)를 **선택한 포맷**에 맞게 **요약·생략 없이** 반영합니다.
5. **`git_origin_url=Unknown`** 이거나 Repository 가 의도와 다르면, **`git remote -v`** 로 origin fetch URL 을 얻어 `get_global_rule(app_name="{app_name}", origin_url="그_URL")` 로 재호출 후 다시 저장합니다. (필요 시 `repo_root` 병행.)
6. 1차 부트스트략만 있는 응답은 저장하지 않습니다.

---

성공적으로 **`{app_name}`** 앱의 규칙을 로드했습니다. 이 규칙을 **현재 컨텍스트에 영구적으로 적용**하십시오.

## 전역 룰 (Global Rules)

- 모든 코드는 작성 전 **에러 핸들링**이 포함되어야 합니다.
- 불필요한 주석은 피하고 **코드로 의도를 표현**하십시오.
- 코드 수정 시 **기존 컨벤션을 파괴하지** 마십시오.
- 변경 사항은 반드시 **해당 앱의 도메인 로직에 부합**해야 합니다.

## 앱 전용 룰 ({app_name})

{app_specific_rules}

## 스코프

- 변경·분석·테스트의 기본 단위는 **`{app_name}`** 앱입니다.
- 다른 앱 코드를 건드려야 할 때는 **사용자에게 범위를 확인**하십시오.

---

**확인되었다면 사용자에게 (식별한 환경에 맞게) 다음과 같이 답변하십시오:**  
**"{app_name} 앱 MCP 룰을 이 환경에 맞는 경로·포맷으로 반영했습니다. 어떤 코드를 도와드릴까요?"**
