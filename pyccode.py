import os
import subprocess
import sys
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


def handle_bash(input: dict) -> str:
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


TOOL_HANDLERS = {
    "bash": handle_bash,
    "read": handle_read,
    "write": handle_write,
    "edit": handle_edit,
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

    while True:
        # 1. Model Chat
        response = client.messages.create(
            model=os.environ.get("MODEL_NAME", "claude-sonnet-4-5-20250929"),
            max_tokens=1024,
            system=SYSTEM,
            messages=history,
            tools=TOOLS
        )

        # 2. Return if no tool_use
        if response.stop_reason != "tool_use":
            return "".join(c.text for c in response.content if c.type == "text")

        # 3. Manage history: assistant content
        assistant_content = []

        for content in response.content:
            # remain the key info in the content
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

        # 4. Use tools
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

        # 5. Manage history: tool use results as user content
        history.append({"role": "user", "content": results})


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