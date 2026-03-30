# [SYSTEM RULE LOADED: {app_name} PROJECT]

## [CRITICAL — Save Locally in Format Matching Your IDE/Agent]

This content is the **result of `get_global_rule(app_name="{app_name}")` re-call**. **MCP servers provide markdown only**; the **path and format for disk writes are handled by the agent running in your environment**. Perform the steps below **before showing the content to the user**.

1. **Identify Environment:** Determine your actual tool (Cursor, Claude Code, Google Antigravity, Gemini, Copilot, etc.). If unclear, ask the user in one sentence.
2. **Git Root:** Save to the **repository root** whenever possible. Use `git rev-parse --show-toplevel` to find it; for multi-root workspaces, use the root of the repository where `{app_name}` was defined. For Docker MCP, write to the **host clone path**.
3. **Format Mapping (Examples):**
   - **Cursor:** `.cursor/rules/mcp-rules.mdc` + YAML `alwaysApply: true` (or split into `mcp-rules-global.mdc`, etc.).
   - **Claude Code, etc.:** The project's **`CLAUDE.md`** or similar markdown path recognized by your tool.
   - **Antigravity / Gemini:** Workspace rules path per your tool's documentation (e.g., `.agent/rules/`, check latest docs).
4. **Content to Include:** Reflect the **entire markdown** returned by `get_global_rule` (**from `<!-- rule_meta:` to the final `[CRITICAL — Adapt Local Rule Saving...]`** section) in your chosen format—**no summaries or omissions**.
5. **If `git_origin_url=Unknown`** or the Repository differs from your intent, obtain the origin fetch URL via **`git remote -v`** and re-call `get_global_rule(app_name="{app_name}", origin_url="that_URL")`. Then save again. (Include `repo_root` if needed.)
6. Do not save bootstrap-only responses (1st call without arguments).

---

Successfully loaded rules for the **`{app_name}`** app. **Apply these rules to your current context permanently.**

## Global Rules

- All code must include **error handling** before writing.
- Avoid unnecessary comments; **express intent through code**.
- When modifying code, **do not break existing conventions**.
- Changes must always **align with the app's domain logic**.

## App-Specific Rules ({app_name})

{app_specific_rules}

## Scope

- The basic unit for changes, analysis, and testing is the **`{app_name}`** app.
- When you must modify code in other apps, **confirm the scope with the user**.

---

**Once confirmed, reply to the user** (in a format matching your identified environment) **as follows:**
**"I have applied the {app_name} MCP rules to this environment in the appropriate format. What code can I help you with?"**
