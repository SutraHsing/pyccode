"""Bash tool: shell command execution."""
import os
import subprocess


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


SCHEMA = {
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
}
