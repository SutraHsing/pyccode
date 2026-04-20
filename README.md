# pyccode

A single-file AI agent CLI that uses the Anthropic Messages API with multi-tool support. Supports interactive REPL and single-prompt modes.

## Features

- **6 built-in tools**: bash, read, write, edit, TodoWrite, run_subagent
- **Subagent system**: Delegate complex subtasks to isolated in-process agents
- **Task tracking**: Built-in todo list with pending/in_progress/completed states
- **Anthropic-compatible**: Works with any provider supporting the Anthropic Messages API

## Installation

```bash
git clone https://github.com/SutraHsing/pyccode.git
cd pyccode
uv sync
```

Requires Python >=3.12.

## Quick Start

```bash
# Interactive REPL (type q/quit/exit to stop)
python pyccode.py

# Single task
python pyccode.py "your task here"
```

## Configuration

Create a `.env` file:

```bash
ANTHROPIC_BASE_URL=https://your-api-endpoint.com/api/anthropic
ANTHROPIC_API_KEY=your-api-key-here
MODEL_NAME=claude-sonnet-4-5-20250929       # optional, defaults to this
ANTHROPIC_TIMEOUT=600                         # optional, seconds (default 600)
```

## Available Tools

| Tool | Description |
|------|-------------|
| **bash** | Execute shell commands (git, ls, find, grep, python, pip, etc.) |
| **read** | Read file contents with line numbers, supports offset/limit |
| **write** | Write content to files, creates parent directories if needed |
| **edit** | Edit files by replacing exact text matches |
| **TodoWrite** | Manage a task list with pending/in_progress/completed states |
| **run_subagent** | Spawn an isolated sub-agent for complex subtasks |

## Dependencies

- `anthropic>=0.75.0`
- `dotenv>=0.9.9`

## Author

- [Sutra Hsing](https://github.com/SutraHsing)
