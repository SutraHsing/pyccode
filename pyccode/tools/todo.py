"""Todo tool: Task / TaskStore dataclasses and the TodoWrite handler."""
from dataclasses import dataclass, field


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


# Module-global, swapped by handle_subagent for sub-agent isolation.
_task_store = TaskStore()


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

SCHEMA = {
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
