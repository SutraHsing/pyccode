import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from http.client import responses
from wsgiref.util import application_uri

from anthropic import Anthropic
from dotenv import load_dotenv

WORKDIR = Path.cwd()
SESSION_ID = uuid.uuid4().hex
LARGE_TOOL_RESULT_THRESHOLD = 50000   # chars
SUMMARY_HEAD_CHARS = 2000              # fixed head slice; meta + end marker keeps total ~2.2KB
TOOL_RESULT_MESSAGE_BUDGET = 200_000   # chars; per-message cap enforced by enforceToolResultBudget
MICROCOMPACT_MAX_TOOL_RESULTS = 10     # trigger threshold (uncleared compactable count)
MICROCOMPACT_KEEP_RECENT = 5           # number of recent uncleared results to preserve
COMPACTABLE_TOOLS = frozenset({"bash", "read", "write", "edit", "TodoWrite", "skill"})
OLD_TOOL_RESULT_PLACEHOLDER = "[Old tool result content cleared]"
TRANSCRIPT_VERSION = "0.1.0"
TRANSCRIPT_DIR = Path.home() / ".pyccode" / "projects"
TRANSCRIPT_CWD = re.sub(r'[^A-Za-z0-9._-]', '-', str(WORKDIR))
TRANSCRIPT_PATH = TRANSCRIPT_DIR / TRANSCRIPT_CWD / f"{SESSION_ID}.jsonl"
TOOL_RESULTS_DIR = TRANSCRIPT_DIR / TRANSCRIPT_CWD / SESSION_ID / "tool-results"
_transcript_last_uuid = None
AUTOCOMPACT_CONTEXT_WINDOW = 200_000       # model's hard limit (input + output combined)
AUTOCOMPACT_OUTPUT_RESERVE = 20_000        # reserved for model response
AUTOCOMPACT_BUFFER = 30_000                # one-turn growth safety margin (lag of reactive trigger)
AUTOCOMPACT_THRESHOLD = AUTOCOMPACT_CONTEXT_WINDOW - AUTOCOMPACT_OUTPUT_RESERVE - AUTOCOMPACT_BUFFER
AUTOCOMPACT_KEEP_RECENT = 4                # messages to preserve after compact
AUTOCOMPACT_MAX_OUTPUT_TOKENS = 16_384     # cap for the summary LLM call
_last_input_tokens = 0                     # updated by chat() after each API response

AUTOCOMPACT_PROMPT = """\
Summarize the conversation above so a fresh agent can continue the
work without re-reading the full transcript. Respond with TEXT ONLY -
do not call any tools.

Cover these 9 sections, in order, each as a short paragraph or bullet
list:

1. Primary Request and Intent
   What the user originally asked for, plus any clarifications or
   scope changes that came up during the conversation.

2. Key Technical Concepts
   Domain knowledge, project conventions, constraints, or definitions
   the agent needs to do the work. Name names (libraries, tools,
   patterns).

3. Files and Code Sections
   Specific files touched, read, or modified. Include function
   signatures, key snippets, and line numbers where relevant.

4. Errors and Fixes
   Bugs hit, root causes identified, and how each was resolved. Quote
   exact error text where useful.

5. Problem Solving
   Decisions made, alternatives considered, trade-offs accepted.
   Include any rejected approaches and why.

6. All User Messages
   Verbatim or near-verbatim list of every user prompt, clarification,
   or piece of feedback. Number them.

7. Pending Tasks
   What's left to do. Be specific - link to acceptance criteria,
   checklists, or open PR comments where applicable.

8. Current Work
   What was being done when context ran out. Name the file being
   edited, the test being run, the question being answered.

9. Optional Next Step
   The single most immediate action to take. Concrete, not aspirational.

Be specific and dense. File paths, function names, exact error strings
- include them. A vague summary forces the next agent to re-read the
transcript, which defeats the point.
"""

_BASE_SYSTEM = f"""You are a helpful AI Agent at {WORKDIR} with some bash tools.
Rules:
* Prefer tools use over prose. Act first, explain briefly after.
* For complex tasks with multiple steps, use the TodoWrite tool to plan and track progress.
"""

SYSTEM = _BASE_SYSTEM + """\
* Subagent: For complex subtasks, use the run_subagent tool to delegate to a sub-agent with isolated context, e.g.:
  run_subagent(prompt="explore src/ and summarize the architecture")
* When to use subagent: A task requires to consume a lot of context(read many files, etc.)
 and can output limit results for the following tasks(file writes done, structured summary, etc.)
"""

TODO_WRITE_TOOL_DESCRIPTION = """\
**When to Use This Tool**: Use this tool proactively in these scenarios:
1. Complex multi-step tasks - When a task requires 3+ distinct steps or careful planning
2. User-initiated tasking - When the user provides multiple tasks, explicitly requests the todo list, or gives new instructions to capture
3. Workflow state management - Mark tasks in_progress BEFORE starting work (one at a time), and mark completed when done (adding any follow-up tasks discovered along the way)

Update the task list. Pass the full list of tasks each time — this replaces the entire list.

**Task States**: Use these states to track progress:
- pending: Task not yet started
- in_progress: Currently working on (limit to ONE task at a time)
- completed: Task finished successfully

**IMPORTANT**: Task descriptions must have two forms:
- content: The imperative form describing what needs to be done (e.g., "Run tests", "Build the project")
- activeForm: The present continuous form shown during execution (e.g., "Running tests", "Building the project")

**Task Management**:
1. Mark a task in_progress right before starting it — only ONE task should be in_progress at a time
2. When a task is done, mark it completed and mark the next task in_progress in the same call
3. Only mark completed when fully finished. If blocked by errors or unresolved issues, keep it in_progress — ask the user for help if needed, but do not prematurely mark it completed\
"""

TOOLS = [
    {
        "name": "bash",
        "description": "Execute a bash command. Use for: git, ls, find, grep, python, pip, and any shell operations. For reading/writing/editing files, prefer the dedicated read/write/edit tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Bash command to execute"
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "read",
        "description": "Read file contents with line numbers. Use for: viewing source code, config files, logs, any text file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read (absolute or relative)"
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based). Default: 1"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read. Default: 2000"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "write",
        "description": "Write content to a file. Creates the file if it does not exist, overwrites it if it does. Creates parent directories if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write (absolute or relative)"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "required": ["file_path", "content"]
        }
    },
    {
        "name": "edit",
        "description": "Edit a file by replacing exact text matches. Finds old_string in the file and replaces it with new_string. The old_string must match exactly (including whitespace and indentation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to edit (absolute or relative)"
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to find in the file"
                },
                "new_string": {
                    "type": "string",
                    "description": "Text to replace old_string with"
                }
            },
            "required": ["file_path", "old_string", "new_string"]
        }
    },
    {
        "name": "TodoWrite",
        "description": TODO_WRITE_TOOL_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Imperative form of the task (e.g., 'Run tests')"
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Task state: pending, in_progress, or completed"
                            },
                            "activeForm": {
                                "type": "string",
                                "description": "Present continuous form shown during execution (e.g., 'Running tests')"
                            }
                        },
                        "required": ["content", "status", "activeForm"]
                    },
                    "description": "Full list of tasks (replaces the entire list each call)"
                }
            },
            "required": ["todos"]
        }
    },
    {
        "name": "skill",
        "description": "Load a skill's detailed instructions by name. Use when the user's request matches a skill's description. Returns the skill's full markdown body and its directory path (for accessing reference files).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill to load"
                }
            },
            "required": ["name"]
        }
    }
]

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

load_dotenv(override=True)

# Read timeout from env, default to 10 minutes (for debugging with breakpoints)
timeout_seconds = int(os.environ.get("ANTHROPIC_TIMEOUT", "600"))

client = Anthropic(
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    timeout=timeout_seconds,
)


# Set up env:
# ANTHROPIC_BASE_URL
# ANTHROPIC_API_KEY
# For example:
# export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
# export ANTHROPIC_API_KEY=${DEEPSEEK_API_KEY}


@dataclass
class Task:
    id: int
    content: str
    status: str = "pending"  # "pending" | "in_progress" | "completed"
    activeForm: str = ""


@dataclass
class TaskStore:
    tasks: list[Task] = field(default_factory=list)
    def write(self, todos: list[dict]) -> str:
        """Replace the entire task list with the provided todos."""
        self.tasks.clear()
        for i, todo in enumerate(todos, start=1):
            self.tasks.append(Task(
                id=i,
                content=todo["content"],
                status=todo["status"],
                activeForm=todo["activeForm"],
            ))
        return self._format()

    def _format(self) -> str:
        if not self.tasks:
            return "(no tasks)"
        icons = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
        return "\n".join(f"  {t.id}. {icons.get(t.status, '[?]')} {t.content}" for t in self.tasks)


_task_store = TaskStore()


def load_skills() -> dict:
    """Load all skill definitions from skills/*/SKILL.md.

    Returns a dict keyed by skill name, each value is:
    {"description": str, "content": str, "path": str (absolute path to skill directory)}.
    The path allows the agent to locate reference files alongside SKILL.md.
    """
    skills = {}
    skills_dir = WORKDIR / "skills"
    if not skills_dir.is_dir():
        return skills
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            continue
        with open(skill_file, "r", encoding="utf-8") as f:
            raw = f.read()
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', raw, re.DOTALL)
        if not m:
            continue
        meta_text, body = m.group(1), m.group(2)
        meta = yaml.safe_load(meta_text) or {}
        name = meta.get("name", entry.name)
        description = meta.get("description", "")
        skills[name] = {"description": description, "content": body.strip(), "path": str(entry)}
    return skills


SKILLS = load_skills()


def handle_bash(input: dict) -> str:
    """Execute a bash command and return its output.

    Runs the given shell command via subprocess, captures stdout and stderr,
    and returns the combined output. Handles timeouts and empty output gracefully.

    Args:
        input: A dict containing a 'command' key with the shell command string
            to execute.

    Returns:
        The combined stdout and stderr output from the command as a string.
    """
    command = input["command"]
    print(f"\033[33m$ {command}\033[0m")
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=300, cwd=os.getcwd()
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        output = "(timeout after 300s)"
    output = output.encode('utf-8', errors='replace').decode('utf-8')
    if not output:
        output = "(empty)"
    print(output)
    return output


def handle_read(input: dict) -> str:
    """Read file contents and return them with line numbers.

    Opens the specified file, extracts a range of lines based on the given
    offset and limit, and formats them with line numbers. Handles common
    file system errors gracefully, returning descriptive error messages.

    Args:
        input: A dict containing the following keys:
            file_path (str): Path to the file to read (absolute or relative).
            offset (int, optional): Line number to start reading from (1-based).
                Defaults to 1.
            limit (int, optional): Maximum number of lines to read.
                Defaults to 2000.

    Returns:
        The file contents with line-number formatting as a string,
        or an error message string if the file cannot be read.
    """
    file_path = input["file_path"]
    offset = input.get("offset", 1)
    limit = input.get("limit", 2000)
    print(f"\033[33mRead: {file_path}\033[0m")
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        selected = lines[offset - 1 : offset - 1 + limit]
        output = "".join(
            f"{i:>6}\t{line}" for i, line in enumerate(selected, start=offset)
        )
    except FileNotFoundError:
        output = f"Error: File not found: {file_path}"
    except IsADirectoryError:
        output = f"Error: Is a directory: {file_path}"
    except PermissionError:
        output = f"Error: Permission denied: {file_path}"
    except Exception as e:
        output = f"Error: {e}"
    if not output:
        output = "(empty)"
    print(output)
    return output


def handle_write(input: dict) -> str:
    """Write content to a file and return a status message.

    Creates the file (and any missing parent directories) if it does not exist,
    or overwrites the existing file. Handles common file system errors gracefully,
    returning descriptive error messages.

    Args:
        input: A dict containing the following keys:
            file_path (str): Path to the file to write (absolute or relative).
            content (str): Content to write to the file.

    Returns:
        A status message string indicating success or describing an error.
    """
    file_path = input["file_path"]
    content = input["content"]
    print(f"\033[33mWrite: {file_path}\033[0m")
    try:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        output = f"OK: Wrote {len(content)} chars to {file_path}"
    except PermissionError:
        output = f"Error: Permission denied: {file_path}"
    except Exception as e:
        output = f"Error: {e}"
    print(output)
    return output


def handle_edit(input: dict) -> str:
    """Edit a file by replacing an exact text match with new text.

    Reads the specified file, locates occurrences of old_string, and replaces
    them with new_string. Handles zero-match and multiple-match cases, as well
    as common file system errors, returning descriptive status or error messages.

    Args:
        input: A dict containing the following keys:
            file_path (str): Path to the file to edit (absolute or relative).
            old_string (str): Exact text to find in the file.
            new_string (str): Text to replace old_string with.

    Returns:
        A status message string indicating how many occurrences were replaced,
        or describing an error.
    """
    file_path = input["file_path"]
    old_string = input["old_string"]
    new_string = input["new_string"]
    print(f"\033[33mEdit: {file_path}\033[0m")
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        count = content.count(old_string)
        if count == 0:
            output = f"Error: old_string not found in {file_path}"
        else:
            content = content.replace(old_string, new_string)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            output = f"OK: Replaced {count} occurrence(s) in {file_path}"
    except FileNotFoundError:
        output = f"Error: File not found: {file_path}"
    except PermissionError:
        output = f"Error: Permission denied: {file_path}"
    except Exception as e:
        output = f"Error: {e}"
    print(output)
    return output


def handle_todo(input: dict) -> str:
    """Replace the task list with the provided todos.

    Args:
        input: A dict containing:
            todos (list[dict]): List of task objects with keys:
                content (str): Imperative task description.
                status (str): One of 'pending', 'in_progress', 'completed'.
                activeForm (str): Present continuous form for display.

    Returns:
        Formatted task list string.
    """
    todos = input["todos"]
    output = _task_store.write(todos)
    print(f"\033[33mTodo: updated {len(todos)} task(s)\033[0m")
    print(output)
    return output


def handle_subagent(input: dict) -> str:
    """Run a sub-agent with isolated context to handle a subtask.

    Spawns an in-process sub-agent that has access to all tools in TOOLS
    (bash, read, write, edit, TodoWrite) but NOT run_subagent itself,
    preventing recursive spawning. The sub-agent gets its own isolated
    task store and conversation history.

    Args:
        input: A dict containing a 'prompt' key with the task for the sub-agent.

    Returns:
        The sub-agent's final text response.
    """
    global _task_store
    prompt = input["prompt"]
    print(f"\033[33m[Subagent] {prompt[:2000]}\033[0m")

    # Swap in an isolated task store for the sub-agent
    main_store = _task_store
    _task_store = TaskStore()

    try:
        # Inject skill metadata into first user message
        if SKILLS:
            skill_info = "\n".join(
                f"- {name}: {info['description']}" for name, info in SKILLS.items()
            )
            prompt = f"<system-reminder>\nAvailable skills:\n{skill_info}\n</system-reminder>\n\n{prompt}"
        messages = [{"role": "user", "content": prompt}]

        while True:
            microcompactMessages(messages)
            response = client.messages.create(
                model=os.environ.get("MODEL_NAME", "claude-sonnet-4-5-20250929"),
                max_tokens=16384,
                system=_BASE_SYSTEM,
                messages=messages,
                tools=TOOLS,
            )

            # Collect assistant content
            assistant_content = []
            for content in response.content:
                if content.type == "text":
                    assistant_content.append({"type": "text", "text": content.text})
                elif content.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": content.id,
                        "name": content.name,
                        "input": content.input,
                    })
            messages.append({"role": "assistant", "content": assistant_content})

            # Return if done
            if response.stop_reason == "end_turn":
                result = "".join(
                    c.text for c in response.content if c.type == "text"
                )
                print("\033[33m[Subagent] Done\033[0m")
                return result

            # Handle truncation
            if response.stop_reason == "max_tokens":
                messages.append({
                    "role": "user",
                    "content": "Continue where you left off.",
                })
                continue

            # Execute tool calls
            results = []
            for content in response.content:
                if content.type == "tool_use":
                    handler = TOOL_HANDLERS.get(content.name)
                    if handler:
                        output = handler(content.input)
                    else:
                        output = f"Error: Unknown tool: {content.name}"
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": content.id,
                        "content": maybePersistLargeToolResult(content.id, output),
                    })
            messages.append({"role": "user", "content": enforceToolResultBudget(results)})
    finally:
        _task_store = main_store


def handle_skill(input: dict) -> str:
    """Load and return a skill's full instructions by name."""
    name = input["name"]
    if name not in SKILLS:
        return f"Error: Unknown skill: {name}. Available: {', '.join(SKILLS.keys()) or '(none)'}"
    print(f"\033[33mSkill: {name}\033[0m")
    skill = SKILLS[name]
    return f"Skill path: {skill['path']}\n\n{skill['content']}"


def _persist_tool_result(tool_use_id: str, output: str) -> str:
    """Write ``output`` to disk and return a preview summary.

    Caller decides whether persistence is warranted (threshold or budget).
    Writes to ``WORKDIR / SESSION_ID / "tool-results" / <safe_id>.<ext>``
    with extension auto-sniffed via ``json.loads``. The returned summary
    uses the format documented on ``maybePersistLargeToolResult``.

    On filesystem failure, returns legacy 50K truncation with an error
    note appended so the chat loop never breaks.
    """
    try:
        try:
            json.loads(output)
            ext = "json"
        except (ValueError, TypeError):
            ext = "txt"

        safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', tool_use_id)
        TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        file_path = TOOL_RESULTS_DIR / f"{safe_id}.{ext}"
        file_path.write_text(output, encoding='utf-8')

        summary = (
            f"[tool_result_persisted]\n"
            f"original_length: {len(output)} chars\n"
            f"persisted_to: {file_path}\n"
            f"\n--- HEAD ---\n"
            f"{output[:SUMMARY_HEAD_CHARS]}\n"
            f"--- end ---"
        )

        print(f"\033[33m[Tool result persisted: {len(output)} chars -> {file_path}]\033[0m")
        return summary
    except Exception as e:
        truncated = output[:LARGE_TOOL_RESULT_THRESHOLD]
        return truncated + f"\n[persist failed: {e}]"


def maybePersistLargeToolResult(tool_use_id: str, output: str) -> str:
    """Persist oversized tool output to a file and return a compact summary.

    If ``len(output) <= LARGE_TOOL_RESULT_THRESHOLD`` the input is returned
    unchanged. Otherwise the full output is written to
    ``WORKDIR / SESSION_ID / "tool-results" / <safe_id>.<ext>`` and a
    head-only summary of ``SUMMARY_HEAD_CHARS`` chars plus small metadata
    is returned. The summary intentionally does not prescribe a downstream
    tool; the agent chooses how to inspect the file (read, grep, bash, etc.).

    On filesystem failure the function falls back to legacy truncation with
    an error note appended, so the chat loop never breaks due to persistence.

    Args:
        tool_use_id: The Anthropic tool_use ID; used as the filename stem.
        output: The full tool output string.

    Returns:
        Either the original ``output`` (under threshold) or a summary string
        referencing the persisted file path (over threshold).
    """
    if len(output) <= LARGE_TOOL_RESULT_THRESHOLD:
        return output
    return _persist_tool_result(tool_use_id, output)


def enforceToolResultBudget(results: list) -> list:
    """Cap total tool_result size in a single user message.

    If the combined ``len(content)`` across all ``tool_result`` blocks
    exceeds ``TOOL_RESULT_MESSAGE_BUDGET``, the largest results are
    persisted to disk (via ``_persist_tool_result``) and replaced with
    preview summaries until the total fits the budget. Already-small
    results (``<= 2 * SUMMARY_HEAD_CHARS``) are skipped because
    re-persisting would not shrink them.

    Runs after the per-result ``maybePersistLargeToolResult`` pass. The
    two compose: large individual results are summarized first, then the
    budget pass cleans up "many medium results" cases.

    Args:
        results: List of ``tool_result`` dicts (each with ``content`` and
            ``tool_use_id`` keys). Mutated in place via index assignment;
            the same list object is returned for convenience.

    Returns:
        The same ``results`` list, possibly with some entries' ``content``
        replaced by preview summaries.
    """
    total = sum(len(r["content"]) for r in results)
    if total <= TOOL_RESULT_MESSAGE_BUDGET:
        return results

    order = sorted(
        range(len(results)),
        key=lambda i: len(results[i]["content"]),
        reverse=True,
    )
    for i in order:
        if total <= TOOL_RESULT_MESSAGE_BUDGET:
            break
        content = results[i]["content"]
        if len(content) <= 2 * SUMMARY_HEAD_CHARS:
            break
        new_content = _persist_tool_result(results[i]["tool_use_id"], content)
        total += len(new_content) - len(content)
        results[i] = {**results[i], "content": new_content}
    return results


def microcompactMessages(history: list) -> list:
    """Clear old reproducible tool_result contents from conversation history.

    Triggered when the count of **uncleared compactable** ``tool_result``
    blocks exceeds ``MICROCOMPACT_MAX_TOOL_RESULTS``. Leaves the most
    recent ``MICROCOMPACT_KEEP_RECENT`` uncleared compactable blocks
    intact and replaces the older ones' ``content`` with
    ``OLD_TOOL_RESULT_PLACEHOLDER``.

    Compactable tools (``COMPACTABLE_TOOLS``) are those whose output the
    agent can reproduce by re-invoking the tool — file reads, bash, etc.
    ``run_subagent`` is excluded because sub-agent outputs are one-shot.

    Counts only uncleared blocks (content != placeholder), so compaction
    fires in batches roughly every ``MAX - KEEP_RECENT`` turns rather
    than every turn. This batches prefix-cache invalidation events.

    Runs once per turn before the API call in both ``chat()`` and
    ``handle_subagent()``. Mutates history in place. Never raises: any
    internal error returns history unchanged so the chat loop is
    unaffected.

    Args:
        history: Conversation history as a list of message dicts.

    Returns:
        The same ``history`` reference (mutated in place).
    """
    try:
        # tool_result blocks carry only tool_use_id; recover name from the matching tool_use.
        tool_use_index = {}
        for msg in history:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_use_index[block.get("id")] = block.get("name")

        uncleared_compactable = []
        for msg_idx, msg in enumerate(history):
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block_idx, block in enumerate(content):
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if block.get("content") == OLD_TOOL_RESULT_PLACEHOLDER:
                    continue
                tool_name = tool_use_index.get(block.get("tool_use_id"))
                if tool_name in COMPACTABLE_TOOLS:
                    uncleared_compactable.append((msg_idx, block_idx))

        if len(uncleared_compactable) <= MICROCOMPACT_MAX_TOOL_RESULTS:
            return history

        to_compact = (
            uncleared_compactable[:-MICROCOMPACT_KEEP_RECENT]
            if MICROCOMPACT_KEEP_RECENT > 0
            else uncleared_compactable
        )
        for msg_idx, block_idx in to_compact:
            history[msg_idx]["content"][block_idx]["content"] = OLD_TOOL_RESULT_PLACEHOLDER

        return history
    except Exception:
        return history


def appendTranscript(role: str, content) -> None:
    """Append one entry to the session transcript JSONL file.

    Writes a single JSON object on its own line at ``TRANSCRIPT_PATH``.
    Updates the module-level ``_transcript_last_uuid`` to form a parent
    chain. Schema: ``type`` / ``uuid`` / ``parentUuid`` / ``timestamp`` /
    ``sessionId`` / ``cwd`` / ``version`` / ``message``.

    Open-write-close per entry for crash safety; no held file handle.
    Never raises: transcript failures print a yellow notice to stderr
    and return, so the chat loop is unaffected.
    """
    global _transcript_last_uuid
    try:
        entry_uuid = uuid.uuid4().hex
        entry = {
            "type": role,
            "uuid": entry_uuid,
            "parentUuid": _transcript_last_uuid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sessionId": SESSION_ID,
            "cwd": str(WORKDIR),
            "version": TRANSCRIPT_VERSION,
            "message": {"role": role, "content": content},
        }
        TRANSCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRANSCRIPT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _transcript_last_uuid = entry_uuid
    except Exception as e:
        print(f"\033[33m[Transcript write failed: {e}]\033[0m", file=sys.stderr)


def _history_append(history: list, role: str, content) -> None:
    """Append a message to history and mirror it to the transcript."""
    history.append({"role": role, "content": content})
    appendTranscript(role, content)


def _callCompactLLM(history: list) -> str:
    """Send history to the model with the compact prompt; return summary text.

    No tools are passed, so the model can only return text. Uses the
    same model as the main agent (MODEL_NAME env). Lets exceptions
    propagate so maybeAutoCompact's try/except can apply its fallback.
    """
    response = client.messages.create(
        model=os.environ.get("MODEL_NAME", "claude-sonnet-4-5-20250929"),
        max_tokens=AUTOCOMPACT_MAX_OUTPUT_TOKENS,
        system="You are a helpful AI assistant tasked with summarizing conversations.",
        messages=history + [{"role": "user", "content": AUTOCOMPACT_PROMPT}],
    )
    return "".join(c.text for c in response.content if c.type == "text")


def _buildCompactSummaryMessage(summary: str) -> str:
    """Wrap the LLM-generated summary with the continuation prefix."""
    return (
        "This session is being continued from a previous conversation "
        "that ran out of context. A compact summary follows. Do not "
        "recap or ask the user what to do next — continue the work "
        "from where it left off.\n\n"
        f"If you need specific details from before compaction (exact "
        f"code snippets, error messages, content you generated), read "
        f"the full transcript at: {TRANSCRIPT_PATH}\n\n"
        "--- COMPACT SUMMARY ---\n"
        f"{summary.strip()}\n"
        "--- END SUMMARY ---"
    )


def maybeAutoCompact(history: list) -> bool:
    """Summarize and shrink history when the previous turn neared the context limit.

    Reactive trigger: reads ``_last_input_tokens`` (set by ``chat()``
    after each API response). If it exceeds ``AUTOCOMPACT_THRESHOLD``,
    calls the model with a 9-section summary prompt and replaces
    history in place with ``[boundary_msg, summary_msg, *recent_N]``.

    Returns True if a compact happened, False otherwise. Never raises:
    on LLM failure or empty summary, prints a yellow notice to stderr
    and returns False without modifying history.

    Args:
        history: Conversation history as a list of message dicts.
            Mutated in place if a compact happens.

    Returns:
        True if history was compacted, False otherwise.
    """
    global _last_input_tokens
    if _last_input_tokens <= AUTOCOMPACT_THRESHOLD:
        return False
    if len(history) < AUTOCOMPACT_KEEP_RECENT + 2:
        return False

    try:
        summary = _callCompactLLM(history)
    except Exception as e:
        print(f"\033[33m[Auto-compact failed: {e}]\033[0m", file=sys.stderr)
        return False

    if not summary or not summary.strip():
        print("\033[33m[Auto-compact failed: empty summary]\033[0m", file=sys.stderr)
        return False

    recent = history[-AUTOCOMPACT_KEEP_RECENT:]
    history.clear()
    _history_append(history, "user", "[compact_boundary]")
    _history_append(history, "user", _buildCompactSummaryMessage(summary))
    for msg in recent:
        history.append(msg)  # already in transcript; don't re-append

    print(f"\033[33m[Auto-compact: history reduced to {len(history)} messages]\033[0m")
    return True


# Maps tool names to their handler functions.
TOOL_HANDLERS = {
    "bash": handle_bash,
    "read": handle_read,
    "write": handle_write,
    "edit": handle_edit,
    "TodoWrite": handle_todo,
    "run_subagent": handle_subagent,
    "skill": handle_skill,
}


def chat(prompt, history=None):
    """Chat with an AI agent that can execute bash commands.

    Sends a prompt to Anthropic's API with bash tool capabilities. Handles tool
    execution iteratively: when the model requests a command, it executes the
    command, captures output, and feeds results back to continue the conversation.

    Args:
        prompt: The user's message to send to the agent.
        history: Optional list of previous messages for context.

    Returns:
        The final text response when the model doesn't request tool execution.
    """
    if history is None:
        history = []
    # Inject skill metadata into first user message
    if not history and SKILLS:
        skill_info = "\n".join(
            f"- {name}: {info['description']}" for name, info in SKILLS.items()
        )
        prompt = f"<system-reminder>\nAvailable skills:\n{skill_info}\n</system-reminder>\n\n{prompt}"
    _history_append(history, "user", prompt)

    rounds_without_todo = 0

    while True:
        # 1. Model Chat
        microcompactMessages(history)
        maybeAutoCompact(history)
        response = client.messages.create(
            model=os.environ.get("MODEL_NAME", "claude-sonnet-4-5-20250929"),
            max_tokens=16384,
            system=SYSTEM,
            messages=history,
            tools=TOOLS + [SUBAGENT_TOOL]
        )

        global _last_input_tokens
        if response.usage and response.usage.input_tokens:
            _last_input_tokens = response.usage.input_tokens

        # 2. Collect assistant content into history
        assistant_content = []
        for content in response.content:
            if content.type == "text":
                assistant_content.append({"type": "text", "text": content.text})
            elif content.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": content.id,
                    "name": content.name,
                    "input": content.input
                })

        _history_append(history, "assistant", assistant_content)

        # 3. Return if model finished naturally (no tool_use, no truncation)
        if response.stop_reason == "end_turn":
            return "".join(c.text for c in response.content if c.type == "text")

        # 4. If truncated (max_tokens), prompt the model to continue
        if response.stop_reason == "max_tokens":
            _history_append(history, "user", "Continue where you left off.")
            continue

        # 5. Use tools
        # results for each tool use
        results = []
        for content in response.content:
            if content.type == "tool_use":
                handler = TOOL_HANDLERS.get(content.name)
                if handler:
                    output = handler(content.input)
                else:
                    output = f"Error: Unknown tool: {content.name}"
                    print(output)

                results.append({
                    "type": "tool_result",
                    "tool_use_id": content.id,
                    "content": maybePersistLargeToolResult(content.id, output),
                })

        # 6. Manage history: tool use results as user content
        _history_append(history, "user", enforceToolResultBudget(results))

        # 7. Round-counter reminder: nudge agent to use todo after 5 rounds
        if any(c.type == "tool_use" and c.name == "TodoWrite" for c in response.content):
            rounds_without_todo = 0
        else:
            rounds_without_todo += 1
        if rounds_without_todo >= 5:
            _history_append(
                history,
                "user",
                "Reminder: You've used tools 5+ times without tracking progress. "
                "Consider using the 'TodoWrite' tool to create a plan or update task status.",
            )
            rounds_without_todo = 0


def main():
    """Entry point for the pyccode CLI."""
    if len(sys.argv) > 1:
        print(chat(sys.argv[1]))
    else:
        # interactive
        history = []
        while True:
            try:
                prompt = input("\033[36m>> \033[0m")
            except KeyboardInterrupt:
                print("\nExiting...")
                break

            if prompt in ('q', 'quit', "exit"):
                print("\nExiting...")
                break

            print(chat(prompt, history))



if __name__ == '__main__':
    main()