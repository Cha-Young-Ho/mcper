# [CRITICAL ACTION REQUIRED: APP_NAME MISSING]

The **`app_name`** parameter is mandatory to load rules for this project.
**Never guess or make up an app_name arbitrarily.** Follow the procedure below exactly.

---

## [Required] Rule Version Check (`check_rule_versions`)

- The MCP tool **`check_rule_versions`** provides **latest rule versions** (integers: `1`, `2`, `3`, …) for **global · repository(pattern-matched) · app** in JSON format.
- Compare **`global_served`**, **`repo_served`**, **`app_served`** etc. in the local rules file header `<!-- rule_meta: … -->` with the server's latest version integers.
- If any version differs, **do not overwrite with guesses**. Instead, **call `get_global_rule` again** and update the local rules file with the **latest content**.

---

## [Required] When User Requests "Get Rules / Check Rules / Sync Rules"

- If the user requests with similar phrasing like **"fetch project rules"**, **"check rules"**, **"get MCP rules"**, do not just display `get_global_rule` result in chat. Secure `app_name` first, then **save the entire 2nd response to disk in the format matching your IDE** (**exception: if user explicitly says to skip saving**).

---

## What is `app_name` (Important)

- **A single identifier from the configuration file**. (Example: `your_app_name`)
- **Do not append branch names or `/master`**. Never call with `your_app_name/master`—use only **`your_app_name`** in the form `get_global_rule(app_name="your_app_name")`.
- Project example: if `config.dev.ini` has `[Global]` section with `app_name = "your_app_name"`, the parameter is **`your_app_name`** alone.

---

## [Step 1] File Search

- Read **`config.dev.ini`** or **`config.ini`** from the project **root directory**.
- (Per project convention) Usually extract **only the value** of the **`app_name`** key under **`[Global]`** section. Remove quotes; use the raw identifier only.
- Once found, immediately **call `get_global_rule(app_name="found_value")`** (**without slashes or suffixes**).

---

## [Step 2] Ask User (If file not found or value not located)

- **Do not search for additional files.**
- Stop immediately and ask the user exactly as follows:

  **"What is the app identifier (app_name) you are working with? Please provide it exactly as it appears in your config file's `app_name`. (Example: `your_app_name` — do not include branch names or `/master`.)"**

- Once the user answers, extract **only the app identifier as written in the INI file** and call **`get_global_rule(app_name="...")`**. If the answer contains `something/master`, use **only the part before `/`**.

---

## Prohibited Actions

- **Do not guess** `app_name` from folder names, previous conversations, or branch names.
- **Do not append `/master` or similar to `app_name`**. (By team convention, the app identifier is a single INI value.)
- If you cannot find both files in [Step 1], **do not search for other ini/json/yaml files**—proceed directly to [Step 2].

---

## [Step 3] Save Final Rules in Format Matching Your IDE/Agent (After `app_name` Confirmed)

- **MCP provides markdown only.** **Adapt paths and file formats to your actual environment** (Cursor / Claude Code / Antigravity / Gemini, etc.).
- Save the **2nd response** from `get_global_rule(app_name="confirmed_value")` to disk **relative to the Git repository root**. (Do not just read—save it.)
  - If only a subfolder is open, use `git rev-parse --show-toplevel` to find the root.
  - For multi-root workspaces, use the repository root where `app_name` was found.
  - For Docker MCP, write to the **host clone path** (not inside the container).
- **Follow the detailed procedure** in the 2nd response's **`[CRITICAL — Adapt Local Rule Saving to Your IDE]`** section.
- **Do not save the bootstrap response** (from the 1st call without arguments).

---

## [Reference] After `app_name` Confirmed: Global + Repository + App (3-tier)

- It is recommended to **re-call with `get_global_rule(app_name="…", origin_url="…")`**. **`origin_url`** should be the **origin fetch URL** (`git@…` or `https://…`) obtained via **`git remote -v`**.
- The response may include **Global rule**(latest) + **Repository rule**(pattern-matched against the above URL and DB) + **App rule**(`app_name` stream) in order.
- Even if the MCP server cannot read Git (e.g., Docker), **providing `origin_url` alone enables Repository rule matching**.
- For additional checks, use **`git status`** etc. If uncertain, **ask the user** for the repository root and current branch.

---

*Next: After securing `app_name`, re-call `get_global_rule(app_name="your_app_name", origin_url=…)` and save according to your tool's instructions (e.g., Cursor saves to **`.cursor/rules/mcp-rules.mdc`**), as described at the end of the 2nd response.*
