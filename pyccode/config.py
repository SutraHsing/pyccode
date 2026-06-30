"""Configuration: constants, system prompts, and the shared Anthropic client.

Leaf module — imports only stdlib + third-party. No intra-package imports.
"""
import os
import re
import uuid
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

# === Paths and session ===
WORKDIR = Path.cwd()
SESSION_ID = uuid.uuid4().hex

# === Tool result persistence (Layer 1 and Layer 2 thresholds) ===
LARGE_TOOL_RESULT_THRESHOLD = 50000   # chars
SUMMARY_HEAD_CHARS = 2000              # fixed head slice; meta + end marker keeps total ~2.2KB
TOOL_RESULT_MESSAGE_BUDGET = 200_000   # chars; per-message cap enforced by enforceToolResultBudget

# === Microcompact (Layer 3 thresholds) ===
MICROCOMPACT_MAX_TOOL_RESULTS = 10     # trigger threshold (uncleared compactable count)
MICROCOMPACT_KEEP_RECENT = 5           # number of recent uncleared results to preserve
COMPACTABLE_TOOLS = frozenset({"bash", "read", "write", "edit", "TodoWrite", "skill"})
OLD_TOOL_RESULT_PLACEHOLDER = "[Old tool result content cleared]"

# === Transcript ===
TRANSCRIPT_VERSION = "0.1.0"
TRANSCRIPT_DIR = Path.home() / ".pyccode" / "projects"
TRANSCRIPT_CWD = re.sub(r'[^A-Za-z0-9._-]', '-', str(WORKDIR))
TRANSCRIPT_PATH = TRANSCRIPT_DIR / TRANSCRIPT_CWD / f"{SESSION_ID}.jsonl"
TOOL_RESULTS_DIR = TRANSCRIPT_DIR / TRANSCRIPT_CWD / SESSION_ID / "tool-results"

# === Auto-compact (Layer 4 thresholds) ===
AUTOCOMPACT_CONTEXT_WINDOW = 200_000       # model's hard limit (input + output combined)
AUTOCOMPACT_OUTPUT_RESERVE = 20_000        # reserved for model response
AUTOCOMPACT_BUFFER = 30_000                # one-turn growth safety margin (lag of reactive trigger)
AUTOCOMPACT_THRESHOLD = AUTOCOMPACT_CONTEXT_WINDOW - AUTOCOMPACT_OUTPUT_RESERVE - AUTOCOMPACT_BUFFER
AUTOCOMPACT_KEEP_RECENT = 4                # messages to preserve after compact
AUTOCOMPACT_MAX_OUTPUT_TOKENS = 16_384     # cap for the summary LLM call

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

# === System prompts ===
BASE_SYSTEM = f"""You are a helpful AI Agent at {WORKDIR} with some bash tools.
Rules:
* Prefer tools use over prose. Act first, explain briefly after.
* For complex tasks with multiple steps, use the TodoWrite tool to plan and track progress.
"""

SYSTEM = BASE_SYSTEM + """\
* Subagent: For complex subtasks, use the run_subagent tool to delegate to a sub-agent with isolated context, e.g.:
  run_subagent(prompt="explore src/ and summarize the architecture")
* When to use subagent: A task requires to consume a lot of context(read many files, etc.)
 and can output limit results for the following tasks(file writes done, structured summary, etc.)
"""

# === Environment and shared Anthropic client ===
load_dotenv(override=True)
timeout_seconds = int(os.environ.get("ANTHROPIC_TIMEOUT", "600"))
client = Anthropic(
    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    timeout=timeout_seconds,
)
