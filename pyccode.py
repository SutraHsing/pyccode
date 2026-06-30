import os
import sys

from pyccode.config import (
    BASE_SYSTEM,
    SYSTEM,
    client,
)
from pyccode.tools import (
    SUBAGENT_TOOL,
    SKILLS,
    TOOLS,
    TOOL_HANDLERS,
    _task_store,
)
from pyccode.context import (
    enforceToolResultBudget,
    history_append,
    maybeAutoCompact,
    maybePersistLargeToolResult,
    microcompactMessages,
)


# Set up env:
# ANTHROPIC_BASE_URL
# ANTHROPIC_API_KEY
# For example:
# export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
# export ANTHROPIC_API_KEY=${DEEPSEEK_API_KEY}


def handle_subagent(input: dict) -> str:
    """Run a sub-agent with isolated context to handle a subtask.

    Spawns an in-process sub-agent that has access to all leaf tools
    (bash, read, write, edit, TodoWrite, skill) but NOT run_subagent itself,
    preventing recursive spawning. The sub-agent gets its own isolated
    task store and conversation history.

    Args:
        input: A dict containing a 'prompt' key with the task for the sub-agent.

    Returns:
        The sub-agent's final text response.
    """
    from pyccode.tools.todo import TaskStore
    from pyccode.tools.skill import SKILLS as _SKILLS
    global _task_store
    prompt = input["prompt"]
    print(f"\033[33m[Subagent] {prompt[:2000]}\033[0m")

    # Swap in an isolated task store for the sub-agent
    main_store = _task_store
    _task_store = TaskStore()

    try:
        # Inject skill metadata into first user message
        if _SKILLS:
            skill_info = "\n".join(
                f"- {name}: {info['description']}" for name, info in _SKILLS.items()
            )
            prompt = f"<system-reminder>\nAvailable skills:\n{skill_info}\n</system-reminder>\n\n{prompt}"
        messages = [{"role": "user", "content": prompt}]

        while True:
            microcompactMessages(messages)
            response = client.messages.create(
                model=os.environ.get("MODEL_NAME", "claude-sonnet-4-5-20250929"),
                max_tokens=16384,
                system=BASE_SYSTEM,
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


# Main-agent dispatch table: leaf handlers + run_subagent.
# handle_subagent references this dict at call time; sub-agent invocations
# pass tools=TOOLS (no SUBAGENT_TOOL), so the model never asks for
# run_subagent even though the dispatch entry exists.
TOOL_HANDLERS = {**TOOL_HANDLERS, "run_subagent": handle_subagent}




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
    history_append(history, "user", prompt)

    rounds_without_todo = 0
    last_input_tokens = 0

    while True:
        # 1. Model Chat
        microcompactMessages(history)
        maybeAutoCompact(history, last_input_tokens)
        response = client.messages.create(
            model=os.environ.get("MODEL_NAME", "claude-sonnet-4-5-20250929"),
            max_tokens=16384,
            system=SYSTEM,
            messages=history,
            tools=TOOLS + [SUBAGENT_TOOL]
        )

        if response.usage and response.usage.input_tokens:
            last_input_tokens = response.usage.input_tokens

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

        history_append(history, "assistant", assistant_content)

        # 3. Return if model finished naturally (no tool_use, no truncation)
        if response.stop_reason == "end_turn":
            return "".join(c.text for c in response.content if c.type == "text")

        # 4. If truncated (max_tokens), prompt the model to continue
        if response.stop_reason == "max_tokens":
            history_append(history, "user", "Continue where you left off.")
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
        history_append(history, "user", enforceToolResultBudget(results))

        # 7. Round-counter reminder: nudge agent to use todo after 5 rounds
        if any(c.type == "tool_use" and c.name == "TodoWrite" for c in response.content):
            rounds_without_todo = 0
        else:
            rounds_without_todo += 1
        if rounds_without_todo >= 5:
            history_append(
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