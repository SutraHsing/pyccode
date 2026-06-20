# Directory Structure

> pyccode is a single-file Python CLI. This spec describes where things live inside `pyccode.py` and the supporting project files.

---

## Project Layout

```
pyccode/
├── pyccode.py              # all application code (~750 lines)
├── pyproject.toml          # entry point: pyccode = "pyccode:main"
├── uv.lock                 # dependency lock
├── .env                    # ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY / MODEL_NAME / ANTHROPIC_TIMEOUT
├── skills/                 # auto-discovered; one dir per skill
│   └── <name>/SKILL.md     # required; YAML frontmatter + body
├── CLAUDE.md               # agent guidance (high-level)
├── README.md               # user docs
└── .trellis/               # Trellis workflow scaffolding
```

There is no package hierarchy. Everything ships in `pyccode.py`.

---

## Module Ordering Inside `pyccode.py`

Top-to-bottom order is load-bearing — earlier sections define names used later. Preserve this layout when inserting new code.

| Lines (approx) | Section | Purpose |
|---|---|---|
| 1–21 | Imports + module constants | `json`, `os`, `re`, `subprocess`, `sys`, `uuid`, dataclass, Path, yaml, Anthropic, dotenv. Then `WORKDIR`, `SESSION_ID`, `LARGE_TOOL_RESULT_THRESHOLD`, `SUMMARY_HEAD_CHARS`, `TOOL_RESULT_MESSAGE_BUDGET`. |
| 23–29 | `_BASE_SYSTEM`, `SYSTEM` | Two-tier system prompt. Subagents get `_BASE_SYSTEM` only. |
| 31–52 | `TODO_WRITE_TOOL_DESCRIPTION` | Long description kept out of the schema literal for readability. |
| 54–182 | `TOOLS`, `SUBAGENT_TOOL` | Anthropic tool-use schemas. `SUBAGENT_TOOL` is separate; only the main agent gets `TOOLS + [SUBAGENT_TOOL]`. |
| 184–212 | Env config + Anthropic client | `load_dotenv(override=True)`, timeout from env, `client = Anthropic(...)`. |
| 228–259 | `Task`, `TaskStore` | In-memory todo tracking. |
| 261 | `_task_store` | Module-global; swapped by `handle_subagent`. |
| 261–292 | `load_skills()` + `SKILLS` | Auto-discovery of `skills/*/SKILL.md`. |
| 294–558 | Tool handlers | `handle_bash`, `handle_read`, `handle_write`, `handle_edit`, `handle_todo`, `handle_subagent`, `handle_skill`. |
| 560–669 | Tool result persistence | `_persist_tool_result` (disk-write + preview builder), `maybePersistLargeToolResult` (per-result wrapper, >50K), `enforceToolResultBudget` (per-message wrapper, >200K total). |
| 671–679 | `TOOL_HANDLERS` | Dispatch dict. Defined AFTER all handlers so all names resolve. |
| 682–780 | `chat(prompt, history)` | Core agentic loop. |
| 782–end | `main()` | CLI entry: single-prompt vs REPL. |

---

## Where New Code Goes

- **New tool**: add a `handle_<name>(input: dict) -> str` function in the handler block; add its schema to `TOOLS` (or to `SUBAGENT_TOOL` if main-agent-only); register in `TOOL_HANDLERS`.
- **New skill**: drop a directory under `skills/<name>/SKILL.md`. No code change needed.
- **New module constant**: top of file, next to `WORKDIR` / `SESSION_ID`.
- **New system-prompt tweak**: edit `_BASE_SYSTEM` (both agents) or `SYSTEM` (main only).

---

## Naming Conventions

- Tool handler functions: `handle_<toolname>` (snake_case), matching the `name` field in the tool schema.
- Tool names exposed to the model: lowercase (`bash`, `read`, `write`, `edit`, `skill`) or legacy stylized (`TodoWrite`, `run_subagent`). Do not rename the stylized ones.
- Module constants: `UPPER_SNAKE_CASE`.
- Tool dispatch entries: key must equal the tool schema `name` exactly.
