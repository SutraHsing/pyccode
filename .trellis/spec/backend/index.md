# Backend Development Guidelines

> Coding specs for the `pyccode/` package. Read the relevant file before editing that area.

---

## File Map

| Guide | Scope | When to Read |
|---|---|---|
| [Directory Structure](./directory-structure.md) | Project + `pyccode/` package layout | Before inserting new code anywhere |
| [Tool Handlers](./tool-handlers.md) | Handler contract, signature, anti-patterns | Before adding or editing a `handle_*` function |
| [Chat Loop](./chat-loop.md) | Agentic loop invariants, tool result persistence, skill injection | Before editing `chat()` or `handle_subagent()` |
| [Permissions](./permissions.md) | Allowlist + flag validator + y/N gate | Before adding commands to `READONLY_ALLOWLIST` or editing handler permission flow |
| [Error Handling](./error-handling.md) | Error-return convention, subagent isolation | Before adding error paths |
| [Logging Guidelines](./logging-guidelines.md) | print / ANSI conventions, prefix table | Before adding operator-facing output |
| [Quality Guidelines](./quality-guidelines.md) | Required + forbidden patterns, code review checklist | Before any non-trivial edit |

---

## Out of Scope

- Database specs. pyccode has no database; the template `database-guidelines.md` was removed.
- Testing framework. There is no test suite; see [quality-guidelines.md](./quality-guidelines.md) for the smoke-test contract.
- Structured logging. See [logging-guidelines.md](./logging-guidelines.md) — pyccode uses plain `print`.
