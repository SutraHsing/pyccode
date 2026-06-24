# Implementation — Refactor pyccode from Monolith to Modular Structure

## Implementation Plan

This document breaks down the refactoring into 5 phases, each with specific tasks, validation steps, and rollback plans.

---

## Phase 1: Extract `config.py` (No Breaking Changes)

**Goal**: Centralize all constants and configuration without changing behavior.

### Tasks

#### 1.1 Create `pyccode/config.py`
- [ ] Create directory structure: `pyccode/`
- [ ] Create `pyccode/__init__.py` (empty, for now)
- [ ] Create `pyccode/config.py` with all constants:
  - Import constants (lines 17-46 from `pyccode.py`)
  - Import `AUTOCOMPACT_PROMPT` (lines 48-86)
  - Import `_BASE_SYSTEM` and `SYSTEM` (lines 88-92)
  - Add `load_env()` function (load `.env` file)
  - Add `get_model_config()` function (return model name)

#### 1.2 Update `pyccode.py`
- [ ] Remove constant definitions (lines 17-92)
- [ ] Add imports: `from pyccode.config import *`
- [ ] Verify all constants still work

### Validation
```bash
# Test basic functionality
python pyccode.py "reply with: pong"

# Expected output:
# > reply with: pong
# Assistant: pong
```

### Rollback
If anything breaks:
```bash
git checkout pyccode.py
rm -rf pyccode/
```

---

## Phase 2: Extract `tools/` Modules

**Goal**: Move all 7 tool handlers to separate modules.

### Tasks

#### 2.1 Create tool registry
- [ ] Create `pyccode/tools/__init__.py`
- [ ] Define `TOOLS` dict (tool definitions for LLM)
- [ ] Define `HANDLERS` dict (function references)

#### 2.2 Extract `bash.py`
- [ ] Create `pyccode/tools/bash.py`
- [ ] Move `handle_bash()` (lines 361-390)
- [ ] Test: `python pyccode.py "run: echo hello"`

#### 2.3 Extract `file.py`
- [ ] Create `pyccode/tools/file.py`
- [ ] Move `handle_read()` (lines 391-434)
- [ ] Move `handle_write()` (lines 435-465)
- [ ] Move `handle_edit()` (lines 466-507)
- [ ] Test: `python pyccode.py "read pyccode.py | head -5"`

#### 2.4 Extract `todo.py`
- [ ] Create `pyccode/tools/todo.py`
- [ ] Move `Task` class (lines 296-303)
- [ ] Move `TaskStore` class (lines 304-327)
- [ ] Move `handle_todo()` (lines 508-527)
- [ ] Test: `python pyccode.py "add task: test"`

#### 2.5 Extract `subagent.py`
- [ ] Create `pyccode/tools/subagent.py`
- [ ] Move `handle_subagent()` (lines 528-617)
- [ ] Import `chat` from parent module (circular dependency risk)
- [ ] Test: `python pyccode.py "run_subagent(prompt='echo hi')"`

#### 2.6 Extract `skill.py`
- [ ] Create `pyccode/tools/skill.py`
- [ ] Move `load_skills()` (lines 328-360)
- [ ] Move `handle_skill()` (lines 618-627)
- [ ] Test: `python pyccode.py "load skill: example"`

#### 2.7 Update `pyccode.py`
- [ ] Remove tool handler functions (lines 361-627)
- [ ] Remove `Task` and `TaskStore` classes (lines 296-327)
- [ ] Import from `tools`: `from pyccode.tools import TOOLS, HANDLERS`
- [ ] Update tool execution to use `HANDLERS[tool_name]`

### Validation
```bash
# Test all tools
python pyccode.py "run: echo hello"
python pyccode.py "read pyccode.py | head -10"
python pyccode.py "write test.txt: hello"
python pyccode.py "read test.txt"
python pyccode.py "add task: test refactoring"
python pyccode.py "load skill: example"
python pyccode.py "run_subagent(prompt='echo hi')"
```

### Rollback
```bash
git checkout pyccode.py
rm -rf pyccode/tools/
```

---

## Phase 3: Extract `context/` Modules

**Goal**: Move context management logic to dedicated modules.

### Tasks

#### 3.1 Create `context/transcript.py`
- [ ] Create `pyccode/context/__init__.py` (empty)
- [ ] Create `pyccode/context/transcript.py`
- [ ] Move `appendTranscript()` (lines 810-842)
- [ ] Move `_history_append()` (lines 843-848)
- [ ] Define `TRANSCRIPT_PATH` and `TRANSCRIPT_VERSION`
- [ ] Import `WORKDIR`, `SESSION_ID` from `config`

#### 3.2 Create `context/layers.py`
- [ ] Create `pyccode/context/layers.py`
- [ ] Move `maybePersistLargeToolResult()` (lines 628-666)
- [ ] Move `enforceToolResultBudget()` (lines 667-692)
- [ ] Move `microcompactMessages()` (lines 693-736)
- [ ] Move `maybeAutoCompact()` (lines 737-809)
- [ ] Move helper functions (`_persist_tool_result`, etc.)
- [ ] Import constants from `config`
- [ ] Import `_history_append` from `transcript`

#### 3.3 Update `pyccode.py`
- [ ] Remove context functions (lines 628-809)
- [ ] Import: `from pyccode.context.layers import maybeAutoCompact, microcompactMessages, enforceToolResultBudget`
- [ ] Import: `from pyccode.context.transcript import appendTranscript`

### Validation
```bash
# Test context management (long conversation)
python pyccode.py  # REPL mode, type 20+ messages
# Expected: auto-compact triggers, context stays within limits
```

### Rollback
```bash
git checkout pyccode.py
rm -rf pyccode/context/
```

---

## Phase 4: Extract `chat.py` and `main.py`

**Goal**: Extract core loop and CLI entry point.

### Tasks

#### 4.1 Create `chat.py`
- [ ] Create `pyccode/chat.py`
- [ ] Move `chat()` function (lines 939-1040)
- [ ] Import: `from .config import SYSTEM, MODEL_NAME`
- [ ] Import: `from .tools import TOOLS, HANDLERS`
- [ ] Import: `from .context.layers import maybeAutoCompact, microcompactMessages, enforceToolResultBudget`
- [ ] Import: `from .context.transcript import appendTranscript`

#### 4.2 Create `main.py`
- [ ] Create `pyccode/main.py`
- [ ] Move `main()` function (lines 1041-1050+)
- [ ] Import: `from .chat import chat`
- [ ] Add argument parsing (if not already)

#### 4.3 Update `pyccode.py`
- [ ] Remove `chat()` and `main()` functions
- [ ] Keep only: imports and a thin wrapper
- [ ] Update to: `from pyccode.main import main`

#### 4.4 Update `pyccode/__init__.py`
- [ ] Add: `from .main import main`
- [ ] Add: `from .chat import chat` (for testing)

### Validation
```bash
# Test CLI interface
python pyccode.py "echo test"

# Test REPL mode
python pyccode.py  # should enter REPL
# Type: exit
```

### Rollback
```bash
git checkout pyccode.py
rm pyccode/chat.py pyccode/main.py
```

---

## Phase 5: Cleanup

**Goal**: Final polish and documentation.

### Tasks

#### 5.1 Remove unused code
- [ ] Remove any remaining duplicate code from `pyccode.py`
- [ ] Remove unused imports
- [ ] Verify `pyccode.py` is now a thin wrapper

#### 5.2 Add docstrings
- [ ] Add module docstring to each `.py` file
- [ ] Add function docstrings (at least: purpose, params, returns)
- [ ] Follow Google docstring format or numpy style

#### 5.3 Update `__init__.py` files
- [ ] Ensure all `__init__.py` files exist
- [ ] Verify imports work correctly
- [ ] Test: `from pyccode import main; main()`

#### 5.4 Update documentation
- [ ] Update `README.md` (if needed)
- [ ] Add "Architecture" section
- [ ] Update "Getting Started" (if changed)

#### 5.5 Final test
- [ ] Run all Phase 1-4 validation tests
- [ ] Run full integration test:
  ```bash
  python pyccode.py <<EOF
  add task: test refactoring
  read pyccode.py | head -20
  run: echo "hello world"
  load skill: example
  run_subagent(prompt='echo hi')
  EOF
  ```

### Rollback
No rollback needed. If issues found, fix bugs.

---

## Testing Strategy

### Unit Tests (Future)

After refactoring, add unit tests:
```python
# tests/test_config.py
def test_constants_defined():
    assert hasattr(config, 'LARGE_TOOL_RESULT_THRESHOLD')

# tests/test_tools/test_bash.py
def test_handle_bash():
    result = handle_bash({"command": "echo hello"})
    assert "hello" in result

# tests/test_context/test_layers.py
def test_microcompact():
    history = [...]
    new_history = microcompactMessages(history)
    assert len(new_history) < len(history)
```

### Integration Tests

Run before each phase:
```bash
# Basic functionality
python pyccode.py "reply with: pong"

# All tools
python pyccode.py "run: echo test"
python pyccode.py "read pyccode.py | head -5"
python pyccode.py "add task: test"

# Long conversation (context management)
python pyccode.py  # REPL, type 30+ messages
```

---

## Timeline Estimate

| Phase | Tasks | Time (hours) |
|-------|-------|-------------|
| Phase 1: config.py | 3 | 1 |
| Phase 2: tools/ | 7 | 3 |
| Phase 3: context/ | 3 | 2 |
| Phase 4: chat.py, main.py | 4 | 2 |
| Phase 5: Cleanup | 5 | 2 |
| **Total** | **22** | **10** |

---

## Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Circular dependency | Medium | High | Careful import planning, test early |
| Broken tools | Low | High | Test each tool individually |
| Context management broken | Low | High | Long conversation test |
| Backward compatibility | Low | Medium | Keep `pyccode.py` as wrapper |
| Performance regression | Low | Low | Measure before/after |

---

## Success Metrics

- [ ] All validation tests pass
- [ ] `python pyccode.py` works identically
- [ ] No behavioral regressions
- [ ] Code is easier to navigate (can find functions quickly)
- [ ] Modules have clear single responsibilities
- [ ] No circular dependencies

---

## Rollback Plan

If major issues found after any phase:
```bash
# Rollback to last working state
git log --oneline  # Find last "Phase X completed" commit
git reset --hard <commit-hash>

# Or rollback individual files
git checkout HEAD~1 pyccode.py
rm -rf pyccode/<new-module>/
```

---

## Next Steps

1. ✅ Review and approve this implementation plan
2. Start Phase 1
3. After each phase, run validation tests
4. Commit with message: `feat: Phase X completed`
5. Move to next phase

---

**Status**: Ready to start Phase 1
**Start Date**: 2026-06-24
**Estimated Completion**: 2026-06-24 (same day, ~10 hours)