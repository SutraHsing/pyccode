# Replace line-number refs with symbol refs in spec

## Goal

Remove fragile `pyccode.py:NNN` line-number references from
`.trellis/spec/backend/*.md`. Replace with stable symbol-based references
(function / class / constant names, or section headings).

## Background

Line numbers rot on every edit. The current specs reference handlers by
`pyccode.py:NNN` which becomes stale after any insertion or deletion
above the referenced line. Symbol names are stable as long as we do not
rename, and they are directly searchable via `grep` / IDE go-to-symbol.

## Requirements

- Replace every `pyccode.py:NNN` reference in `.trellis/spec/backend/*.md`
  with a symbol reference (e.g. `see handle_read`, `in handle_subagent`).
- `directory-structure.md` currently uses a Markdown table whose first
  column is line ranges. Restructure as an ordered list grouped by
  section name, dropping the line ranges entirely. Preserve the
  load-bearing top-to-bottom ordering.
- For the one reference that points at an unnamed code branch
  (`logging-guidelines.md` row "unknown-tool branch (pyccode.py:698)"),
  point at the enclosing function (`chat()`'s unknown-tool fallback)
  instead.
- Do not touch `.trellis/spec/guides/` — those are generic thinking
  guides with no project-specific line refs.

## Acceptance Criteria

- [ ] `grep -rn 'pyccode\.py:[0-9]' .trellis/spec/backend/` returns zero
      matches.
- [ ] `grep -rn '[0-9]–[0-9]' .trellis/spec/backend/directory-structure.md`
      returns zero matches (no surviving line ranges).
- [ ] Each former line reference still points at a meaningful anchor
      (function / class / constant / section).
- [ ] Specs read naturally — no awkward "(in pyccode.py)" filler where a
      bare symbol name would do.

## Out of Scope

- Rewriting spec content beyond the reference substitution.
- Updating other docs (CLAUDE.md, README.md) — they do not currently
  use line refs.
- Adding new spec files.
