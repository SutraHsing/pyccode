# Directory Structure

> pyccode is a single-file Python CLI. This spec describes where things live inside `pyccode.py` and the supporting project files.

---

## Project Layout

```
pyccode/
├── pyccode.py              # all application code
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

## Module Ordering Inside `pyccode.py`

Top-to-bottom order is load-bearing — earlier sections define names used later. Preserve this ordering when inserting new code.

1. **Imports + module constants** — `json`, `os`, `re`, `subprocess`, `sys`, `uuid`, dataclass, datetime, Path, yaml, Anthropic, dotenv. Then `WORKDIR`, `SESSION_ID`, `LARGE_TOOL_RESULT_THRESHOLD`, `SUMMARY_HEAD_CHARS`, `TOOL_RESULT_MESSAGE_BUDGET`, `MICROCOMPACT_MAX_TOOL_RESULTS`, `MICROCOMPACT_KEEP_RECENT`, `COMPACTABLE_TOOLS`, `OLD_TOOL_RESULT_PLACEHOLDER`, `TRANSCRIPT_VERSION`, `TRANSCRIPT_DIR`, `TRANSCRIPT_CWD`, `TRANSCRIPT_PATH`, `TOOL_RESULTS_DIR`, `_transcript_last_uuid`, `AUTOCOMPACT_CONTEXT_WINDOW`, `AUTOCOMPACT_OUTPUT_RESERVE`, `AUTOCOMPACT_BUFFER`, `AUTOCOMPACT_THRESHOLD`, `AUTOCOMPACT_KEEP_RECENT`, `AUTOCOMPACT_MAX_OUTPUT_TOKENS`, `_last_input_tokens`, `AUTOCOMPACT_PROMPT`.
2. **`_BASE_SYSTEM`, `SYSTEM`** — Two-tier system prompt. Subagents get `_BASE_SYSTEM` only.
3. **`TODO_WRITE_TOOL_DESCRIPTION`** — Long description kept out of the schema literal for readability.
4. **`TOOLS`, `SUBAGENT_TOOL`** — Anthropic tool-use schemas. `SUBAGENT_TOOL` is separate; only the main agent gets `TOOLS + [SUBAGENT_TOOL]`.
5. **Env config + Anthropic client** — `load_dotenv(override=True)`, timeout from env, `client = Anthropic(...)`.
6. **`Task`, `TaskStore`** — In-memory todo tracking.
7. **`_task_store`** — Module-global; swapped by `handle_subagent`.
8. **`load_skills()` + `SKILLS`** — Auto-discovery of `skills/*/SKILL.md`.
9. **Tool handlers** — `handle_bash`, `handle_read`, `handle_write`, `handle_edit`, `handle_todo`, `handle_subagent`, `handle_skill`.
10. **Tool result persistence + transcript + auto-compact** — `_persist_tool_result` (disk-write + preview builder), `maybePersistLargeToolResult` (per-result wrapper, >50K), `enforceToolResultBudget` (per-message wrapper, >200K total), `microcompactMessages` (per-turn wrapper, >10 uncleared compactable in whole history), `appendTranscript` (JSONL side-output of every `history.append`), `_history_append` (combined in-memory + transcript writer used by `chat()`), `maybeAutoCompact` (per-turn LLM summarization when previous turn's input_tokens > 150K), `_callCompactLLM` (private summary call helper), `_buildCompactSummaryMessage` (private summary wrapper).
11. **`TOOL_HANDLERS`** — Dispatch dict. Defined AFTER all handlers so all names resolve.
12. **`chat(prompt, history)`** — Core agentic loop.
13. **`main()`** — CLI entry: single-prompt vs REPL.

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
