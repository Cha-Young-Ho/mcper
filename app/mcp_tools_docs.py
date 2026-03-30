"""MCP tool descriptions for admin UI (Tools tab + dashboard)."""

from __future__ import annotations

from typing import Any

# Order = sidebar / dashboard display order
MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_global_rule",
        "one_liner": "Retrieve global / repository / app rules as markdown from DB (required on workspace entry)",
        "title": "get_global_rule — Retrieve Rules",
        "summary": (
            "Retrieves **global · repository (URL pattern) · app** rules stored in Postgres as markdown. "
            "If `app_name` is provided, **it is recommended to pass the origin URL obtained via `git remote -v` as `origin_url`** (Docker MCP can also match Repository rules). "
            "Otherwise, the server reads the origin based on `repo_root`."
        ),
        "params": [
            "app_name (optional): INI app identifier. If absent, **global rules only**.",
            "version (optional): Omit·null·latest → latest. If numeric, that version (falls back to latest if not found). "
            "Applied to global only when app_name is absent; applied to **app rules only** when present (global·repo are always latest).",
            "origin_url (optional, recommended if app_name provided): origin fetch URL from `git remote -v`. Can also pass full output (server extracts URL).",
            "repo_root (optional): Path for server Git metadata. If omitted, uses `GIT_REPO_ROOT` or server CWD.",
        ],
        "notes": [
            "Unlike publish, this only retrieves. Version management is auto-incremented by publish_* tools on the server.",
            "If `origin_url` is present, it takes priority in repository matching. API/web pattern rules can be applied regardless of server Git failures.",
            "When app_name is provided, response includes local storage procedure. MCP provides markdown only.",
            "Whether to include `__default__` app stream alongside dedicated apps is **per-app** configuration (/admin app card·board). If no app row exists, falls back to **global default** on Global rules board.",
            "Whether to include Repository `default` stream with matched patterns is **per-pattern** configuration (/admin Repository rules card).",
        ],
        "examples": [
            "Initial bootstrap (app unknown): `get_global_rule()`",
            "Recommended: `get_global_rule(app_name=\"your_app_name\", origin_url=\"git@github.com:org/repo.git\")`",
            "Three-part + remote full line: `get_global_rule(app_name=\"your_app_name\", origin_url=\"origin  git@github.com:org/r.git (fetch)\")`",
            "Server Git path: `get_global_rule(app_name=\"your_app_name\", repo_root=\"/path/to/repo\")`",
            "Specific app version: `get_global_rule(app_name=\"your_app_name\", version=3)`",
            "Global only with specific version: `get_global_rule(version=2)`",
        ],
    },
    {
        "name": "check_rule_versions",
        "one_liner": "Query only the latest rule version numbers from server DB as JSON (refresh with get_global_rule if mismatched with local)",
        "title": "check_rule_versions — Check Versions",
        "summary": (
            "Returns **only the latest version number (integer)** for global / (optional) app / (optional) repository matching results. "
            "Use this to compare against local rule file's rule_meta·team notes and update to **latest content if different**."
        ),
        "params": [
            "app_name (optional): If provided, includes that app stream·repo matching.",
            "origin_url (optional): `git remote -v` origin fetch URL — used for repository version determination.",
            "repo_root (optional): Server Git auxiliary path.",
        ],
        "notes": [
            "Version is represented as integer only: 1,2,3… (not string format v1).",
            "`mcp_include_app_default` is true/false only when `app_name` is present; null otherwise (reflects per-app·global defaults). `mcp_include_repo_default` is based on matched repository pattern.",
        ],
        "examples": [
            '`check_rule_versions()`',
            '`check_rule_versions(app_name="your_app_name", origin_url="git@github.com:org/repo.git")`',
        ],
    },
    {
        "name": "publish_global_rule",
        "one_liner": "Save a new version of global rules (version number auto-assigned by server)",
        "title": "publish_global_rule — Global New Version",
        "summary": "Adds one new version to global rules. Version number is auto-assigned by the server.",
        "params": [
            "body (required): Complete markdown. Stored immutably as the next global version (1,2,3…).",
        ],
        "notes": [
            "Clients cannot specify the version.",
        ],
        "examples": [
            '`publish_global_rule(body="# New Global Rules\\n\\n- …")`',
        ],
    },
    {
        "name": "publish_app_rule",
        "one_liner": "Save a new version of app-specific rules (version number auto-assigned by server)",
        "title": "publish_app_rule — App Rule New Version",
        "summary": "Adds one new version to a specific app_name stream. Versions increment sequentially per app starting from 1.",
        "params": [
            "app_name (required): Examples: your_app_name, __default__.",
            "body (required): Markdown for that app (repo/domain guide as a single block).",
        ],
        "notes": [
            "Version argument is not provided here either.",
        ],
        "examples": [
            '`publish_app_rule(app_name="your_app_name", body="## your_app_name\\n\\n- …")`',
        ],
    },
    {
        "name": "append_to_app_rule",
        "one_liner": "Append markdown to the latest app rule content and save as new version",
        "title": "append_to_app_rule — Append to App Rule",
        "summary": (
            "Appends `append_markdown` to the **latest** app_rule_versions content of the given `app_name` and saves it as the **next version**. "
            "If the app does **not exist in DB**, creates **version 1** with only the provided content; otherwise appends to the latest, creating versions 2, 3, …."
        ),
        "params": [
            "app_name (required): Example: your_app_name.",
            "append_markdown (required): Markdown to append **after** existing latest content (error if empty).",
        ],
        "notes": [
            "Tailored for requests like 'add ~~ to app rules'. For full replacement, use `publish_app_rule`.",
        ],
        "examples": [
            '`append_to_app_rule(app_name="your_app_name", append_markdown="\\n## New\\n\\n- item")`',
        ],
    },
    {
        "name": "publish_repo_rule",
        "one_liner": "Save a new version of repository rules per origin URL pattern (version auto-assigned by server)",
        "title": "publish_repo_rule — Repository Rule New Version",
        "summary": (
            "Adds a new version to the pattern stream that matches the `git remote` origin URL as a **substring**. "
            "Empty pattern serves as fallback when other patterns don't match."
        ),
        "params": [
            "pattern (required): String that matches if contained in URL (empty string = fallback stream).",
            "body (required): Complete markdown.",
        ],
        "notes": [
            "Versions increment independently per pattern starting from 1. sort_order is maintained by admin on first version creation or from existing stream.",
        ],
        "examples": [
            '`publish_repo_rule(pattern="api", body="## API\\n\\n- …")`',
            '`publish_repo_rule(pattern="", body="## Fallback\\n\\n- …")`',
        ],
    },
    {
        "name": "upload_spec_to_db",
        "one_liner": "INSERT specification content and related file paths into specs table",
        "title": "upload_spec_to_db — Save Specification",
        "summary": "INSERTs planning/specification content and metadata into the specs table.",
        "params": [
            "content, app_target, base_branch (required)",
            "related_files: List or JSON array string, optional",
            "title (optional): Specification title to display in admin list",
        ],
        "notes": [],
        "examples": [
            '`upload_spec_to_db(content="…", app_target="your_app_name", base_branch="main", related_files=["a.php"], title="결제기획")`',
        ],
    },
    {
        "name": "search_spec_and_code",
        "one_liner": "Keyword search specifications content and file paths per app (JSON result)",
        "title": "search_spec_and_code — Search Specifications",
        "summary": "ILIKE search on specification content and related file paths within a specific app_target. Returns JSON with up to 50 results.",
        "params": [
            "query, app_target (required)",
        ],
        "notes": [],
        "examples": [
            '`search_spec_and_code(query="결제", app_target="your_app_name")`',
        ],
    },
    {
        "name": "push_spec_chunks_with_embeddings",
        "one_liner": "Directly reflect locally-embedded specification chunks in spec_chunks (fallback for worker load)",
        "title": "push_spec_chunks_with_embeddings — Local Vector Insertion",
        "summary": (
            "When the server Celery queue is long or embedding GPU is a bottleneck, agents create vectors of the **same dimension** and insert them all at once. "
            "Existing chunks for that spec_id are deleted first, then replaced."
        ),
        "params": [
            "spec_id (required): specs.id",
            "chunks_json: JSON array string — each element contains content, embedding(float[]), metadata(optional)",
        ],
        "notes": [
            "Vector dimension and model must match server `embedding.dim`·`embedding.provider` and corresponding model fields (local_model·openai_model·localhost_model·bedrock, etc.).",
            "Pattern recommended: first create spec row with `upload_spec_to_db`, then populate chunks only with this tool.",
        ],
        "examples": [
            '`push_spec_chunks_with_embeddings(spec_id=1, chunks_json="[{\\"content\\":\\"…\\",\\"embedding\\":[…]}]")`',
        ],
    },
    {
        "name": "push_code_index",
        "one_liner": "Push code AST/symbol index into Celery worker queue (embedding in worker)",
        "title": "push_code_index — Code Graph Indexing",
        "summary": (
            "Accepts nodes and edges JSON, enqueues `index_code_batch` task. "
            "Existing nodes matching `file_paths` are deleted first, then re-inserted."
        ),
        "params": [
            "app_target (required)",
            "file_paths: List of paths or JSON array string",
            "nodes: stable_id, file_path, symbol_name, kind, content",
            "edges: source_stable_id, target_stable_id, relation (e.g., CALLS)",
        ],
        "notes": ["Requires CELERY_BROKER_URL + worker container"],
        "examples": [],
    },
    {
        "name": "analyze_code_impact",
        "one_liner": "Find seed code node by query and collect upstream/downstream from call graph",
        "title": "analyze_code_impact — Impact Analysis (Graph)",
        "summary": "Finds seed node via pgvector+FTS, then collects upstream/downstream using BFS on code_edges, returns JSON.",
        "params": ["query", "app_target"],
        "notes": ["push_code_index로 인덱스가 있어야 의미 있음"],
        "examples": [],
    },
    {
        "name": "find_historical_reference",
        "one_liner": "Find past spec chunks similar to new spec text and return related_files",
        "title": "find_historical_reference — Similar Spec Reference",
        "summary": "Returns top N spec_chunks and related file paths by embedding similarity (for Few-shot reference).",
        "params": ["new_spec_text", "app_target", "top_n (optional, default 5)"],
        "notes": ["Requires spec chunks index (Celery index_spec) to be built first"],
        "examples": [],
    },
]


def tools_with_counts(counts: dict[str, int]) -> tuple[list[dict[str, Any]], int]:
    """Attach call_count to each tool; compute total."""
    total = 0
    out: list[dict[str, Any]] = []
    for t in MCP_TOOLS:
        c = int(counts.get(t["name"], 0))
        total += c
        row = {**t, "call_count": c}
        out.append(row)
    return out, total
