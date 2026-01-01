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

TOOLS = [{
    "name": "bash",

    "description": """Execute bash command. Command pattern:
* Read files: cat, grep, find, ls, head, tail, etc.
* Write files: Write files: echo '...' > file, sed -i, cat << 'EOF' > file, etc.
* Other commands: git, etc.
* Subagent: python pyccode.py '<task description>' (spawns isolated agent, returns summary)""",

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
}]

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
def chat(prompt, history=None):
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

        for content in response.content: # TODO: how many contents possible?
            if content.type == "text": # TODO: Seems just append the whole content is ok
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
                command = content.input["command"]
                print(f"\033[33m$ {command}\033[0m")  # Yellow color for commands

                # Execute the command
                try:
                    result = subprocess.run(
                        command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=300,
                        cwd=os.getcwd()
                    )
                    output = result.stdout+result.stderr
                except subprocess.TimeoutExpired:
                    output = "(timeout after 300s)"

                print(output or "(empty)")

                results.append({
                    "type": "tool_result",
                    "tool_use_id": content.id,
                    "content": output[:50000] # Truncate if too long
                })

        # 5. Manage history: tool use results as user content
        history.append({"role": "user", "content": results})



if __name__ == '__main__':
    if len(sys.argv) > 1:
        chat(sys.argv[1])
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



