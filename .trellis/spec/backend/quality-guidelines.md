# Quality Guidelines

> Code standards for `pyccode.py`. Single-file project, so the rules are tight.

---

## Required Patterns

- **Google-style docstring on every handler.** One-line summary, then `Args:` / `Returns:`. See `handle_read` as the reference.
- **Handler signature `def handle_<name>(input: dict) -> str`**. No kwargs, no optional params. Register in `TOOL_HANDLERS` after definition.
- **Tool schema and handler kept in sync.** Adding a tool means three edits: schema in `TOOLS`, handler function, entry in `TOOL_HANDLERS`. Forgetting any one fails silently or loudly.
- **Constants at the top.** No module-level mutable state except `_task_store` (which has documented swap semantics in `handle_subagent`).
- **`uv run python -c "import pyccode"`** must succeed after every edit. There is no test suite; this is the smoke test.

---

## Forbidden Patterns

- **Raising from a handler.** Convert to `"Error: ..."` string. See [error-handling.md](./error-handling.md).
- **`output[:50000]` style truncation.** Use `maybePersistLargeToolResult`. See [chat-loop.md](./chat-loop.md).
- **`import *`.** Explicit imports only.
- **New package dependencies** without updating `pyproject.toml` and `uv.lock`.
- **Splitting `pyccode.py` into modules.** Single-file is a design constraint, not an accident.
- **Backwards-compat shims.** The project has no external consumers; rename freely.
- **Line-number references in specs.** They rot on every edit. Reference symbols (function / class / constant names) or section headings instead.

---

## Comment Policy

- Default to no comments. Named identifiers carry the meaning.
- One short docstring per function is the ceiling for prose.
- Do not write comments that reference the current task ("added in PR #123", "TODO: refactor later"). Those go in commit messages or issue trackers.

---

## Testing

There is no test suite. The contract is:

1. `uv run python -c "import pyccode"` succeeds.
2. `uv run python pyccode.py "small task"` completes without traceback.
3. `uv run python pyccode.py` enters REPL, `q` exits cleanly.

Any change that breaks the above is not shippable.

---

## Code Review Checklist

- [ ] Handler has a docstring matching the `Args:` / `Returns:` shape.
- [ ] Handler returns `str` only, never raises.
- [ ] New constants placed at the top with the others.
- [ ] `import pyccode` still works.
- [ ] No `output[:50000]` introduced or reintroduced.
- [ ] If adding a tool: schema + handler + dispatch entry all present.
- [ ] No new package without `pyproject.toml` + `uv.lock` update.
- [ ] New operator-facing output reuses an existing prefix from [logging-guidelines.md](./logging-guidelines.md) or extends the table.
- [ ] New spec docs reference symbols, not line numbers.
