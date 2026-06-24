"""Tool registry: schemas + handler dispatch table.

Leaf tools are imported eagerly. ``handle_subagent`` is imported lazily by
``pyccode.chat`` because it depends on chat-time helpers (microcompact,
budget enforcement) that live in ``pyccode.context.layers`` — importing it
here would create a circular dependency.
"""
from .bash import handle_bash, SCHEMA as BASH_SCHEMA
from .file import handle_read, handle_write, handle_edit, SCHEMAS as FILE_SCHEMAS
from .todo import Task, TaskStore, _task_store, handle_todo, SCHEMA as TODO_SCHEMA
from .skill import load_skills, SKILLS, handle_skill, SCHEMA as SKILL_SCHEMA

# Subagent schema (handler is wired in pyccode.chat to avoid circular import).
SUBAGENT_TOOL = {
    "name": "run_subagent",
    "description": (
        "Spawn a sub-agent to handle a complex subtask in isolation. "
        "The sub-agent has access to bash, read, write, edit, and TodoWrite tools "
        "but cannot spawn further sub-agents. "
        "IMPORTANT: The sub-agent shares NO context with you — it only sees the prompt you write. "
        "Your prompt must be self-contained and include all relevant information the sub-agent needs "
        "(file paths, prior findings, constraints, goals). Be generous with context rather than terse. "
        "Do not assume the sub-agent knows anything from your conversation history."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The task for the sub-agent",
            }
        },
        "required": ["prompt"],
    },
}

# Schemas sent to the model for the main agent (includes run_subagent).
TOOLS = [BASH_SCHEMA, *FILE_SCHEMAS, TODO_SCHEMA, SKILL_SCHEMA]

# Schemas for the sub-agent (no run_subagent — prevents recursion).
TOOLS_FOR_SUBAGENT = list(TOOLS)

# Dispatch table for the leaf tools. Subagent handler is added by
# pyccode.chat at chat-loop construction time.
TOOL_HANDLERS = {
    "bash": handle_bash,
    "read": handle_read,
    "write": handle_write,
    "edit": handle_edit,
    "TodoWrite": handle_todo,
    "skill": handle_skill,
}
