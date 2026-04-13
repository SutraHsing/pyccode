import os
import subprocess
import sys
from dataclasses import dataclass, field
from http.client import responses
from wsgiref.util import application_uri

from anthropic import Anthropic
from dotenv import load_dotenv

SYSTEM = f"""You are a helpful AI Agent at {os.getcwd()} with some bash tools.
Rules:
* Prefer tools use over prose. Act first, explain briefly after.
* Subagent: For complex subtasks, spawn subagent to keep the main agent context clean, e.g.:
  python pyccode.py "explore src/ and summarize the architecture"
* When to use subagent: A task requires to consume a lot of context(read many files, etc.)
 and can output limit results for the following tasks(file writes done, structured summary, etc.)
* Todo workflow: 'create' to plan, 'next' to advance. After creating tasks, call 'next' to start the first task. After finishing each task, call 'next' to complete it and start the next. Always call 'next' before starting a task's work.
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
    }
]

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
    _next_id: int = 1

    def write(self, todos: list[dict]) -> str:
        """Replace the entire task list with the provided todos."""
        self.tasks.clear()
        self._next_id = 1
        for todo in todos:
            self.tasks.append(Task(
                id=self._next_id,
                content=todo["content"],
                status=todo["status"],
                activeForm=todo["activeForm"],
            ))
            self._next_id += 1
        return self._format()

    def _format(self) -> str:
        if not self.tasks:
            return "(no tasks)"
        icons = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
        return "\n".join(f"  {t.id}. {icons.get(t.status, '[?]')} {t.content}" for t in self.tasks)


_task_store = TaskStore()


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


# Maps tool names to their handler functions.
TOOL_HANDLERS = {
    "bash": handle_bash,
    "read": handle_read,
    "write": handle_write,
    "edit": handle_edit,
    "TodoWrite": handle_todo,
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
    history.append({"role": "user", "content": prompt})

    rounds_without_todo = 0

    while True:
        # 1. Model Chat
        response = client.messages.create(
            model=os.environ.get("MODEL_NAME", "claude-sonnet-4-5-20250929"),
            max_tokens=16384,
            system=SYSTEM,
            messages=history,
            tools=TOOLS
        )

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

        history.append({"role": "assistant", "content": assistant_content})

        # 3. Return if model finished naturally (no tool_use, no truncation)
        if response.stop_reason == "end_turn":
            return "".join(c.text for c in response.content if c.type == "text")

        # 4. If truncated (max_tokens), prompt the model to continue
        if response.stop_reason == "max_tokens":
            history.append({
                "role": "user",
                "content": "Continue where you left off."
            })
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
                    "content": output[:50000]
                })

        # 6. Manage history: tool use results as user content
        history.append({"role": "user", "content": results})

        # 7. Round-counter reminder: nudge agent to use todo after 5 rounds
        if any(c.type == "tool_use" and c.name == "TodoWrite" for c in response.content):
            rounds_without_todo = 0
        else:
            rounds_without_todo += 1
        if rounds_without_todo >= 5:
            history.append({
                "role": "user",
                "content": (
                    "Reminder: You've used tools 5+ times without tracking progress. "
                    "Consider using the 'TodoWrite' tool to create a plan or update task status."
                )
            })
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