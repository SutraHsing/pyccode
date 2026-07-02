# Directory Structure

> pyccode is a Python package CLI. The `pyccode.py` at the repo root is a 5-line thin wrapper that imports `main` from the `pyccode/` package and runs it.

---

## Project Layout

```
pyccode/
├── pyccode.py              # thin entry wrapper (5 lines)
├── pyproject.toml          # entry point: pyccode = "pyccode:main"
├── uv.lock                 # dependency lock
├── .env                    # ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY / MODEL_NAME / ANTHROPIC_TIMEOUT
├── skills/                 # auto-discovered; one dir per skill
│   └── <name>/SKILL.md     # required; YAML frontmatter + body
├── CLAUDE.md               # agent guidance (high-level)
├── README.md               # user docs
├── .trellis/               # Trellis workflow scaffolding
└── pyccode/                # the actual package
    ├── __init__.py         # re-exports main
    ├── __main__.py         # enables `python -m pyccode`
    ├── main.py             # CLI dispatch (single-prompt vs REPL)
    ├── chat.py             # chat() + handle_subagent() + TOOL_HANDLERS
    ├── config.py           # constants, system prompts, Anthropic client
    ├── tools/
    │   ├── __init__.py     # TOOLS / TOOL_HANDLERS / SUBAGENT_TOOL registry
    │   ├── bash.py
    │   ├── file.py         # read / write / edit
    │   ├── skill.py
    │   └── todo.py         # Task / TaskStore / handle_todo
    └── context/
        ├── __init__.py     # public API re-exports only
        ├── layers.py       # 4-layer context management
        └── transcript.py   # JSONL transcript logging
```

### On-Disk Artifacts Outside the Project

pyccode writes session-scoped artifacts under `~/.pyccode/`, never inside
the project directory:

```
~/.pyccode/projects/<sanitized-cwd>/
├── <sessionId>.jsonl              # transcript (append-only conversation log)
└── <sessionId>/
    └── tool-results/
        ├── <safe_id>.txt          # full output for >50K or budget-persisted results
        └── <safe_id>.json
```

`<sanitized-cwd>` collapses non-`[A-Za-z0-9._-]` in `str(WORKDIR)` to
`-`. `<sessionId>` is a process-level `uuid4().hex` that doubles as
both the transcript filename stem and the tool-results directory name
(filesystems allow a file and directory with the same stem to
coexist).

---

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `pyccode.config` | Constants (`WORKDIR`, `SESSION_ID`, thresholds, `TRANSCRIPT_*`, `AUTOCOMPACT_*`), system prompts (`BASE_SYSTEM`, `SYSTEM`), `load_dotenv`, shared `client = Anthropic(...)`. Leaf module. |
| `pyccode.tools.*` | One file per leaf tool, each exporting a handler + `SCHEMA`. `__init__.py` assembles `TOOLS`, `TOOL_HANDLERS` (leaf only), `SUBAGENT_TOOL`, and re-exports `SKILLS`, `_task_store`. |
| `pyccode.context.transcript` | `appendTranscript`, `history_append`, `_transcript_last_uuid` (chain state). |
| `pyccode.context.layers` | `_persist_tool_result` (private), `maybePersistLargeToolResult`, `enforceToolResultBudget`, `microcompactMessages`, `maybeAutoCompact`, plus private compact helpers. |
| `pyccode.chat` | `chat()` main loop + `handle_subagent()` sub-agent loop. Builds the run_subagent-aware `TOOL_HANDLERS` locally. |
| `pyccode.main` | CLI dispatch — single-prompt mode (`pyccode "<task>"`) vs REPL (`pyccode`). |
| `pyccode.__init__` / `pyccode.__main__` | Package entry: re-export `main` so `pyccode = "pyccode:main"` entry point and `python -m pyccode` both work. |

### Import Direction (no cycles)

```
main → chat → tools → config
              ↘ context → config
```

All intra-package imports go downward. If a lower layer needs a higher
one, pass it as a parameter (see `handle_subagent` lazy-importing
`TaskStore` / `SKILLS` inside the function body).

---

## Where New Code Goes

- **New leaf tool**: create `pyccode/tools/<name>.py` exporting `handle_<name>` + `SCHEMA`; register both in `pyccode/tools/__init__.py` (`TOOLS` list and `TOOL_HANDLERS` dict).
- **New main-agent-only tool** (sub-agent can't see): same as above, plus add to `SUBAGENT_TOOL` exclusion in `chat.py` if applicable.
- **New skill**: drop a directory under `skills/<name>/SKILL.md`. No code change needed.
- **New module constant**: `pyccode/config.py`, grouped with related constants.
- **New system-prompt tweak**: edit `BASE_SYSTEM` (both agents) or `SYSTEM` (main only) in `config.py`.
- **New context-management layer**: add to `pyccode/context/layers.py`; expose via `pyccode/context/__init__.py` if it should be public API.

---

## Naming Conventions

- Tool handler functions: `handle_<toolname>` (snake_case), matching the `name` field in the tool schema.
- Tool names exposed to the model: lowercase (`bash`, `read`, `write`, `edit`, `skill`) or legacy stylized (`TodoWrite`, `run_subagent`). Do not rename the stylized ones.
- Module constants: `UPPER_SNAKE_CASE`.
- Tool dispatch entries: key must equal the tool schema `name` exactly.
