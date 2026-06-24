# Design — Refactor pyccode from Monolith to Modular Structure

## Architecture Overview

The refactoring follows a simple principle: **group by responsibility, avoid patterns**. Each module will have a single, clear purpose. No factories, no dependency injection, no abstract base classes — just clean file organization.

## Module Dependencies

```
main.py
  └── chat.py
      ├── config.py (constants, prompts)
      ├── tools/ (all tool handlers)
      ├── context/layers.py (4-layer management)
      └── context/transcript.py (logging)
```

**Key constraint**: No circular dependencies. All imports go downward.

## Detailed Module Design

### 1. `pyccode/config.py`

**Purpose**: Centralize all configuration, constants, and system prompts.

**Exports**:
```python
# Constants
LARGE_TOOL_RESULT_THRESHOLD = 50000
SUMMARY_HEAD_CHARS = 2000
TOOL_RESULT_MESSAGE_BUDGET = 200_000
MICROCOMPACT_MAX_TOOL_RESULTS = 10
MICROCOMPACT_KEEP_RECENT = 5
COMPACTABLE_TOOLS = frozenset({"bash", "read", "write", "edit", "TodoWrite", "skill"})

# Context management
AUTOCOMPACT_CONTEXT_WINDOW = 200_000
AUTOCOMPACT_OUTPUT_RESERVE = 20_000
AUTOCOMPACT_BUFFER = 30_000
AUTOCOMPACT_THRESHOLD = AUTOCOMPACT_CONTEXT_WINDOW - AUTOCOMPACT_OUTPUT_RESERVE - AUTOCOMPACT_BUFFER
AUTOCOMPACT_KEEP_RECENT = 4
AUTOCOMPACT_MAX_OUTPUT_TOKENS = 16_384
AUTOCOMPACT_PROMPT = "..."  # the 9-section prompt template

# System prompts
SYSTEM = "..."  # the full system prompt
```

**Functions**:
- `load_env()` - load environment variables from `.env`
- `get_model_config()` - return model name, API endpoint, etc.

**No imports**: This is a leaf module (constants only).

---

### 2. `pyccode/main.py`

**Purpose**: CLI entry point, argument parsing.

**Functions**:
```python
def main():
    """Parse arguments and dispatch to chat() or REPL."""
    # argparse setup
    # single-prompt mode: chat(prompt, ...)
    # REPL mode: interactive loop
```

**Imports**:
- `from .chat import chat`
- `from .config import ...`

**No other logic**: Just CLI interface.

---

### 3. `pyccode/chat.py`

**Purpose**: Core agent loop, tool orchestration, LLM interaction.

**Functions**:
```python
def chat(prompt, history=None):
    """Main agent loop. Returns assistant response."""
    # Build system prompt
    # Call LLM
    # Parse tool_calls
    # Execute tools
    # Enforce budgets
    # Auto-compact
    # Return response
```

**Imports**:
- `from .config import SYSTEM, MODEL_NAME`
- `from .tools import ALL_TOOLS`  # tool registry
- `from .context.layers import maybeAutoCompact, microcompactMessages`
- `from .context.transcript import appendTranscript`

**No state**: State is passed via parameters (`history`).

---

### 4. `pyccode/tools/__init__.py`

**Purpose**: Tool registry, tool definitions.

**Exports**:
```python
# Tool definitions (for LLM)
TOOLS = {
    "bash": {"name": "bash", "description": "Execute shell commands", ...},
    "read": {"name": "read", "description": "Read file contents", ...},
    # ... all 7 tools
}

# Tool handlers (for execution)
HANDLERS = {
    "bash": handle_bash,
    "read": handle_read,
    # ... all 7 handlers
}
```

**Imports**:
- From `bash.py`, `file.py`, `todo.py`, `subagent.py`, `skill.py`

---

### 5. `pyccode/tools/bash.py`

**Purpose**: Shell command execution.

**Functions**:
```python
def handle_bash(input: dict) -> str:
    """Execute shell command and return output."""
    # Validate input
    # Run subprocess
    # Return stdout/stderr
```

**Imports**:
- `subprocess`
- No pyccode internal imports (leaf module)

---

### 6. `pyccode/tools/file.py`

**Purpose**: File operations (read, write, edit).

**Functions**:
```python
def handle_read(input: dict) -> str:
    """Read file contents with offset/limit support."""

def handle_write(input: dict) -> str:
    """Write content to file (creates parent dirs)."""

def handle_edit(input: dict) -> str:
    """Edit file by replacing exact text matches."""
```

**Imports**:
- `pathlib.Path`
- No pyccode internal imports (leaf module)

---

### 7. `pyccode/tools/todo.py`

**Purpose**: Todo list management (Task, TaskStore, TodoWrite tool).

**Classes**:
```python
@dataclass
class Task:
    """Represents a task in the todo list."""
    id: str
    description: str
    status: str  # "pending" | "in_progress" | "completed"

class TaskStore:
    """Stores and manages tasks."""

def handle_todo(input: dict) -> str:
    """Handle TodoWrite tool actions."""
```

**Imports**:
- `dataclasses`, `uuid`, `datetime`
- No pyccode internal imports (leaf module)

---

### 8. `pyccode/tools/subagent.py`

**Purpose**: Subagent delegation (run_subagent tool).

**Functions**:
```python
def handle_subagent(input: dict) -> str:
    """Spawn isolated subagent for complex subtasks."""
    # Create new session
    # Run chat() with isolated history
    # Return summary
```

**Imports**:
- `from ..chat import chat`
- `uuid`

---

### 9. `pyccode/tools/skill.py`

**Purpose**: Skill loading and skill tool.

**Functions**:
```python
def load_skills() -> dict:
    """Discover and load all SKILL.md files."""

def handle_skill(input: dict) -> str:
    """Load a skill's full instructions."""
```

**Imports**:
- `pathlib.Path`, `yaml`
- No pyccode internal imports (leaf module)

---

### 10. `pyccode/context/layers.py`

**Purpose**: 4-layer context management.

**Functions**:
```python
def maybePersistLargeToolResult(tool_use_id: str, output: str) -> str:
    """Persist large tool results to file."""

def enforceToolResultBudget(results: list) -> list:
    """Enforce per-message budget with greedy persistence."""

def microcompactMessages(history: list) -> list:
    """Replace old tool results with placeholders."""

def maybeAutoCompact(history: list) -> bool:
    """LLM-driven summary when context nears limit."""
```

**Imports**:
- `from ..config import AUTOCOMPACT_*`, `LARGE_TOOL_RESULT_THRESHOLD`, etc.
- `from .transcript import _history_append`  # for boundary/summary messages
- `from anthropic import Anthropic`  # for summary call

---

### 11. `pyccode/context/transcript.py`

**Purpose**: JSONL transcript logging and history management.

**Functions**:
```python
def appendTranscript(role: str, content) -> None:
    """Append message to transcript JSONL."""

def _history_append(history: list, role: str, content) -> None:
    """Helper: append to history and transcript."""
```

**Exports**:
- `TRANSCRIPT_PATH` (computed path constant)
- `TRANSCRIPT_VERSION` (for format compatibility)

**Imports**:
- `from ..config import WORKDIR, SESSION_ID`
- `pathlib.Path`
- `datetime`

---

### 12. `pyccode/utils/__init__.py`

**Purpose**: General utility functions.

**Functions**:
```python
# Path helpers
def sanitize_path(path: str) -> str: ...
def get_project_cwd() -> Path: ...

# String helpers
def truncate(text: str, max_chars: int) -> str: ...
```

**Note**: Initially empty. Add helpers as needed during refactoring.

---

### 13. `pyccode/__init__.py`

**Purpose**: Package initialization, main exports.

**Exports**:
```python
# Main entry point (backward compat)
from .main import main

# Core API (optional, for testing)
from .chat import chat
```

---

## Refactoring Strategy

### Phase 1: Extract `config.py` (No Breaking Changes)

1. Create `pyccode/config.py` with all constants
2. Update `pyccode.py` to import from `config`
3. Test: `python pyccode.py` still works

### Phase 2: Extract `tools/` Modules

1. Create `pyccode/tools/__init__.py` with tool registry
2. Extract each tool handler to its own file
3. Update `pyccode.py` to import from `tools`
4. Test: all tools still work

### Phase 3: Extract `context/` Modules

1. Create `pyccode/context/transcript.py`
2. Move transcript-related functions there
3. Create `pyccode/context/layers.py`
4. Move 4-layer context management there
5. Test: context management still works

### Phase 4: Extract `chat.py` and `main.py`

1. Create `pyccode/chat.py` with `chat()` function
2. Create `pyccode/main.py` with `main()` function
3. Update `pyccode.py` to import from `main`
4. Test: CLI still works

### Phase 5: Cleanup

1. Remove unused code from `pyccode.py`
2. Add `__init__.py` files
3. Update `README.md` (if needed)
4. Final test: all functionality preserved

## File Migration Plan

| From (pyccode.py lines) | To Module | Lines |
|-------------------------|-----------|-------|
| 1-110 (imports, constants) | `config.py` | ~110 |
| 296-327 (Task, TaskStore) | `tools/todo.py` | ~30 |
| 328-627 (tool handlers) | `tools/*.py` | ~300 |
| 628-666 (persistence) | `context/layers.py` | ~40 |
| 667-692 (budget) | `context/layers.py` | ~25 |
| 693-736 (microcompact) | `context/layers.py` | ~45 |
| 737-809 (auto-compact) | `context/layers.py` | ~70 |
| 810-842 (transcript) | `context/transcript.py` | ~35 |
| 843-938 (chat loop) | `chat.py` | ~95 |
| 939-1041 (main) | `main.py` | ~100 |

## Risk Mitigation

### 1. Git History

```bash
git commit -am "feat: add config module (Phase 1)"
git commit -am "feat: extract tools modules (Phase 2)"
# ... after each phase
```

### 2. Testing After Each Phase

```bash
# Basic sanity check
python pyccode.py "reply with: pong"

# Tool usage
python pyccode.py "read pyccode.py | head -10"

# Todo list
python pyccode.py "add a task: test refactoring"

# Subagent
python pyccode.py "run_subagent(prompt='list skills')"

# Context management (long conversation)
python pyccode.py  # REPL mode, type 20+ messages
```

### 3. Backward Compatibility

Keep `pyccode.py` as a thin wrapper:

```python
# pyccode.py (after refactoring)
from pyccode.main import main

if __name__ == "__main__":
    main()
```

This ensures existing scripts and workflows break nothing.

## Success Criteria

1. ✓ All functionality preserved
2. ✓ `python pyccode.py` works identically
3. ✓ Modules have clear single responsibilities
4. ✓ No circular dependencies
5. ✓ Code is easier to navigate
6. ✓ Future extensions can add new modules cleanly

## Open Questions

1. Should `skills/` be moved into `pyccode/` or stay at root?
   - **Decision**: Keep at root for now (existing workflows depend on it)

2. Should we add type hints?
   - **Decision**: Yes, but gradually (not blocking refactoring)

3. Should we add docstrings to all functions?
   - **Decision**: Yes, PRD requirement (not blocking refactoring)

## References

- PRD: `.trellis/tasks/refactor-project-structure/prd.md`
- Current code: `pyccode.py` (40KB)
- PEP 8: https://peps.python.org/pep-0008/