"""Skill tool: SKILL.md auto-discovery and the skill loader handler."""
import re

import yaml

from pyccode.config import WORKDIR


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


def handle_skill(input: dict) -> str:
    """Load and return a skill's full instructions by name."""
    name = input["name"]
    if name not in SKILLS:
        return f"Error: Unknown skill: {name}. Available: {', '.join(SKILLS.keys()) or '(none)'}"
    print(f"\033[33mSkill: {name}\033[0m")
    skill = SKILLS[name]
    return f"Skill path: {skill['path']}\n\n{skill['content']}"


SCHEMA = {
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
