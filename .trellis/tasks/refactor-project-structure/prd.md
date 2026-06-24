# Refactor pyccode from Monolith to Modular Structure

## Goal

Restructure the pyccode.py monolith into a clean, maintainable modular structure while preserving all existing functionality, trellis workflow, and keeping the design simple without over-engineering.

## Background

pyccode started as a single-file (40KB) CLI agent with 4-layer context management, 7 tools, subagent system, and skills integration. As features have grown (auto-compact, transcript logging, skill system, etc.), the monolithic structure is becoming harder to maintain:

- 40KB+ single file with mixed concerns
- Hard to locate specific functionality
- Testing is difficult
- Future extensions will make this worse

However, we want to avoid over-engineering. The goal is **clean organization, not architectural patterns**. The current structure works well; we just need better file organization.

## Current Structure Analysis

### Main Components in pyccode.py

1. **Context Management Layer** (4 layers):
   - `maybePersistLargeToolResult()` - per-result size cap
   - `enforceToolResultBudget()` - per-message budget
   - `microcompactMessages()` - per-turn count cap
   - `maybeAutoCompact()` - LLM-driven summary

2. **Tool Handlers** (7 tools):
   - `handle_bash()` - shell command execution
   - `handle_read()` - file reading
   - `handle_write()` - file writing
   - `handle_edit()` - text editing
   - `handle_todo()` - todo list management
   - `handle_subagent()` - subagent delegation
   - `handle_skill()` - skill loading

3. **Data Models**:
   - `Task` class - task representation
   - `TaskStore` class - todo list storage

4. **Transcript & Logging**:
   - `appendTranscript()` - JSONL logging
   - `_history_append()` - history management
   - Transcript directory handling

5. **Core Loop**:
   - `chat()` - main agent loop
   - `main()` - CLI entry point

6. **Configuration & Constants**:
   - Model configuration
   - Threshold constants
   - System prompts

## Requirements

### Functional

- All existing functionality must be preserved
- No behavioral changes
- CLI interface unchanged
- Environment variables and config unchanged
- Skills system works identically
- Trellis workflow unchanged

### Module Organization

Proposed structure:

```
pyccode/
├── pyccode/
│   ├── __init__.py          # Package init, exports
│   ├── main.py              # CLI entry point (main())
│   ├── chat.py              # Core chat loop (chat())
│   ├── config.py            # Constants, environment vars, system prompts
│   ├── tools/
│   │   ├── __init__.py      # Tool registry
│   │   ├── bash.py          # handle_bash
│   │   ├── file.py          # handle_read, handle_write, handle_edit
│   │   ├── todo.py          # handle_todo, Task, TaskStore
│   │   ├── subagent.py      # handle_subagent
│   │   └── skill.py         # handle_skill, load_skills
│   ├── context/
│   │   ├── __init__.py      # Context management init
│   │   ├── layers.py        # 4-layer context management
│   │   └── transcript.py    # Transcript logging
│   └── utils/
│       ├── __init__.py      # Utility functions
│       └── path.py          # Path helpers (TRANSCRIPT_PATH, etc.)
├── tests/                   # Test files (optional, can add later)
├── skills/                  # Skills directory (unchanged)
├── pyccode.py              # Legacy entry point (maintains backward compat)
└── setup requirements      # Existing files
```

### Module Responsibilities

#### `pyccode.main`
- `main()` function only
- Argument parsing
- REPL vs single-prompt mode

#### `pyccode.chat`
- `chat()` function
- Core agent loop logic
- Tool orchestration

#### `pyccode.config`
- All constants (LARGE_TOOL_RESULT_THRESHOLD, AUTOCOMPACT_*, etc.)
- Environment variable loading
- System prompt templates
- Model configuration

#### `pyccode.tools`
- Tool handler implementations
- Tool definitions (name, description, input schema)
- Each tool in its own file for clarity

#### `pyccode.context.layers`
- All 4 context management layers
- `maybePersistLargeToolResult()`
- `enforceToolResultBudget()`
- `microcompactMessages()`
- `maybeAutoCompact()`

#### `pyccode.context.transcript`
- `appendTranscript()`
- `_history_append()`
- Transcript path handling

#### `pyccode.utils`
- Helper functions
- Path utilities
- Common operations

### Constraints

- **No external dependencies added**
- **No architectural patterns** (no factories, no dependency injection)
- **Keep imports simple** - avoid circular dependencies
- **Backward compatibility** - `pyccode.py` still works as entry point
- **Testability** - modules should be testable in isolation (but no test framework required)

## Acceptance Criteria

1. [ ] All existing functionality preserved
2. [ ] CLI interface unchanged (`python pyccode.py` works)
3. [ ] Environment variables still work
4. [ ] Skills system works identically
5. [ ] Trellis workflow unchanged
6. [ ] Code is clearly organized by concern
7. [ ] No circular dependencies
8. [ ] Imports are clean and explicit
9. [ ] Documentation in docstrings for each module
10. [ ] Backward compatible entry point maintained

## Non-Functional

- Code should be readable and maintainable
- Comments should explain **why**, not **what**
- Follow PEP 8 style
- Keep changes minimal and focused

## Risk Mitigation

- **Test after each module split** - run CLI to ensure functionality preserved
- **Incremental changes** - don't rewrite everything at once
- **Keep original as backup** - commit each step
- **Document changes** - update README if needed

## Success Metrics

- Code is easier to navigate (can find functionality quickly)
- Modules have clear, single responsibilities
- No behavioral regressions
- Future extensions can add new tools/modules cleanly