# pyccode

A single-file AI agent CLI that uses the Anthropic Messages API with multi-tool and skill support. Supports interactive REPL and single-prompt modes.

## Features

- **7 built-in tools**: bash, read, write, edit, TodoWrite, skill, run_subagent
- **Skill loading**: Auto-discovers `skills/*/SKILL.md` files and lets the agent load detailed instructions on demand
- **Subagent system**: Delegate complex subtasks to isolated in-process agents
- **Task tracking**: Built-in todo list with pending/in_progress/completed states
- **Four-layer context management**:
  - **Per result (>50K chars)**: written to `~/.pyccode/projects/<sanitized-cwd>/<sessionId>/tool-results/<id>.{txt|json}` (never inside the project) and replaced in conversation with a ~2KB head-only summary
  - **Per message (>200K chars total)**: largest results persisted first until under budget
  - **Per turn (>10 uncleared compactable results in history)**: oldest replaced with `[Old tool result content cleared]`, keeping the most recent 5; excludes `run_subagent` (one-shot outputs)
  - **Per turn (previous input_tokens > 150K)**: history is LLM-summarized into a 9-section compact summary; replaced with `[boundary, summary, *last_4_messages]` so long sessions continue past the context window
- **Transcript logging**: every main-agent turn is mirrored to `~/.pyccode/projects/<sanitized-cwd>/<sessionId>.jsonl` as append-only JSONL with a `parentUuid` chain, so past sessions can be inspected with `cat` / `grep` / `jq`. Write-only in MVP — resume is a future task.
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
| **skill** | Load a skill's full markdown instructions and skill directory path by name |
| **run_subagent** | Spawn an isolated sub-agent for complex subtasks |

## Skills

Add skills under `skills/<skill-name>/SKILL.md`. Each skill file must start with YAML frontmatter:

```markdown
---
name: example-skill
description: Use when the agent needs this specific guidance.
---

# Example Skill

Detailed instructions go here.
```

When skills are present, pyccode injects their names and descriptions into the first user message. The agent can then call the `skill` tool to load the full instructions and the skill directory path, which allows reference files beside `SKILL.md` to be used as needed.

## Dependencies

- `anthropic>=0.75.0`
- `dotenv>=0.9.9`

## Author

- [Sutra Hsing](https://github.com/SutraHsing)
