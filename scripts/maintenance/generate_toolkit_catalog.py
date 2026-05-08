#!/usr/bin/env python3
"""Generate packaged toolkit metadata from the plugin skill and agent catalog."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SKILLS = ROOT / "plugin" / "skills"
PLUGIN_AGENTS = ROOT / "plugin" / "agents"
ROOT_SKILL = ROOT / "skill" / "SKILL.md"
TOP_LEVEL_SKILLS = ROOT / "skills-catalog"
DATA_MODULE = ROOT / "src" / "mcp_stata" / "toolkit_catalog_data.py"
PLUGIN_README = ROOT / "plugin" / "README.md"
SKILL_FRONTMATTER_KEYS = {"name", "description"}
AGENT_FRONTMATTER_KEYS = {"name", "description"}
ROOT_SKILL_ID = "stata-toolkit"
PROMPTS = [
    {
        "id": "replicate_result",
        "description": "Prompt template for replication and robustness checks.",
    },
    {
        "id": "audit_dataset",
        "description": "Prompt template for structured dataset audits.",
    },
    {
        "id": "review_table",
        "description": "Prompt template for publication-quality table review.",
    },
    {
        "id": "debug_do_file",
        "description": "Prompt template for debugging failing Stata code.",
    },
    {
        "id": "design_causal_spec",
        "description": "Prompt template for causal design review.",
    },
    {
        "id": "prepare_referee_response",
        "description": "Prompt template for referee-response reruns.",
    },
]
RESOURCES = [
    {"uri": "stata://data/summary", "description": "Structured summarize output for the default session."},
    {"uri": "stata://data/metadata", "description": "Structured describe output for the default session."},
    {"uri": "stata://graphs/list", "description": "Graph metadata for the default session."},
    {"uri": "stata://variables/list", "description": "Variable metadata for the default session."},
    {"uri": "stata://results/stored", "description": "Stored r()/e()/s() results for the default session."},
    {"uri": "stata://project/manifest", "description": "Project-level metadata for the installed toolkit."},
    {"uri": "stata://session/{session_id}/state", "description": "Composite session snapshot for an explicit session id."},
    {"uri": "stata://session/{session_id}/logs", "description": "Recent background log references for a session."},
    {"uri": "stata://session/{session_id}/graphs", "description": "Graph metadata for an explicit session id."},
    {"uri": "stata://research/checklists/{topic}", "description": "Packaged workflow references and checklists."},
    {"uri": "stata://evals/report/latest", "description": "The most recent scored eval report, when available."},
]


def parse_frontmatter(text: str, *, path: Path, allowed_keys: set[str]) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise ValueError(f"{path} is missing YAML frontmatter")
    _, rest = text.split("---\n", 1)
    if "\n---\n" not in rest:
        raise ValueError(f"{path} frontmatter is not terminated")
    frontmatter, body = rest.split("\n---\n", 1)
    meta: dict[str, str] = {}
    for raw_line in frontmatter.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"{path} has an invalid frontmatter line: {raw_line}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        meta[key] = value.strip('"')
    unknown = set(meta) - allowed_keys
    if unknown:
        keys = ", ".join(sorted(unknown))
        raise ValueError(f"{path} has unsupported frontmatter keys: {keys}")
    missing = allowed_keys - set(meta)
    if missing:
        keys = ", ".join(sorted(missing))
        raise ValueError(f"{path} is missing required frontmatter keys: {keys}")
    return meta, body.lstrip("\n")


def load_manifest(path: Path) -> dict:
    if not path.exists():
        raise ValueError(f"Missing sidecar manifest: {path}")
    return json.loads(path.read_text())


def render_full_markdown(*, name: str, description: str, body: str) -> str:
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        "---",
        "",
        body.rstrip(),
    ]
    return "\n".join(lines) + "\n"


def titleize(identifier: str) -> str:
    return " ".join(part.capitalize() for part in identifier.split("-"))


def write_openai_yaml(skill_dir: Path, manifest: dict, *, description: str) -> str:
    agents_dir = skill_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    path = agents_dir / "openai.yaml"
    data = {
        "display_name": manifest.get("display_name", titleize(skill_dir.name)),
        "short_description": manifest.get("short_description", description),
        "default_prompt": manifest.get(
            "default_prompt",
            f"Use the {skill_dir.name} skill to handle this Stata workflow.",
        ),
    }
    lines = [f"{key}: {json.dumps(value)}" for key, value in data.items()]
    path.write_text("\n".join(lines) + "\n")
    return str(path.relative_to(ROOT))


def load_skill_docs() -> list[dict]:
    docs = []
    for path in sorted(PLUGIN_SKILLS.glob("*/SKILL.md")):
        raw = path.read_text()
        meta, body = parse_frontmatter(
            raw,
            path=path,
            allowed_keys=SKILL_FRONTMATTER_KEYS,
        )
        manifest = load_manifest(path.parent / "manifest.json")
        skill_id = meta["name"]
        docs.append(
            {
                "id": skill_id,
                "name": skill_id,
                "description": meta["description"],
                "version": manifest["version"],
                "allowed_tools": manifest.get("allowed_tools", []),
                "argument_hint": manifest.get("argument_hint", ""),
                "supported_agents": manifest.get(
                    "supported_agents",
                    ["claude", "codex", "gemini", "cursor", "windsurf", "vscode"],
                ),
                "trigger_text": manifest.get("trigger_text", meta["description"]),
                "invocation_type": manifest.get("invocation_type", "context-skill"),
                "references": manifest.get("references", []),
                "scripts": manifest.get("scripts", []),
                "body": body,
                "path": str(path.relative_to(ROOT)),
                "openai_yaml_path": write_openai_yaml(path.parent, manifest, description=meta["description"]),
            }
        )
    for item in docs:
        item["content"] = render_full_markdown(
            name=item["name"],
            description=item["description"],
            body=item["body"],
        )
    return docs


def load_agent_docs() -> list[dict]:
    docs = []
    for path in sorted(PLUGIN_AGENTS.glob("*.md")):
        raw = path.read_text()
        meta, body = parse_frontmatter(
            raw,
            path=path,
            allowed_keys=AGENT_FRONTMATTER_KEYS,
        )
        manifest = load_manifest(path.with_suffix(".manifest.json"))
        agent_id = meta["name"]
        docs.append(
            {
                "id": agent_id,
                "name": agent_id,
                "description": meta["description"],
                "version": manifest["version"],
                "supported_agents": manifest.get("supported_agents", ["claude"]),
                "trigger_text": manifest.get("trigger_text", meta["description"]),
                "tools": manifest.get("tools", []),
                "body": body,
                "path": str(path.relative_to(ROOT)),
            }
        )
    for item in docs:
        item["content"] = render_full_markdown(
            name=item["name"],
            description=item["description"],
            body=item["body"],
        )
    return docs


def build_data_module(skills: list[dict], agents: list[dict]) -> str:
    return (
        '"""Generated toolkit catalog data. Do not edit by hand."""\n\n'
        f"SKILLS = {json.dumps(skills, indent=2)}\n\n"
        f"AGENTS = {json.dumps(agents, indent=2)}\n\n"
        f"PROMPTS = {json.dumps(PROMPTS, indent=2)}\n\n"
        f"RESOURCES = {json.dumps(RESOURCES, indent=2)}\n\n"
        'SKILL_BY_ID = {item["id"]: item for item in SKILLS}\n'
        'AGENT_BY_ID = {item["id"]: item for item in AGENTS}\n'
    )


def sync_root_skill(skills: list[dict]) -> None:
    root_doc = next(item for item in skills if item["id"] == ROOT_SKILL_ID)
    ROOT_SKILL.parent.mkdir(parents=True, exist_ok=True)
    ROOT_SKILL.write_text(
        render_full_markdown(
            name=root_doc["name"],
            description=root_doc["description"],
            body=root_doc["body"],
        )
    )


def sync_top_level_skill_catalog(skills: list[dict]) -> None:
    mirrored = [
        item
        for item in skills
        if item["invocation_type"] == "context-skill" and item["id"] != ROOT_SKILL_ID
    ]
    for doc in mirrored:
        slug = doc["id"].removeprefix("stata-")
        path = TOP_LEVEL_SKILLS / slug / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_full_markdown(
                name=doc["name"],
                description=doc["description"],
                body=doc["body"],
            )
        )


def sync_readme(skills: list[dict], agents: list[dict]) -> None:
    text = PLUGIN_README.read_text()

    model_invoked = [item for item in skills if item["invocation_type"] == "context-skill"]
    slash = [item for item in skills if item["invocation_type"] == "slash-command"]

    model_table = ["| Skill | Trigger |", "|---|---|"]
    for item in model_invoked:
        model_table.append(f"| `{item['id']}` | {item['trigger_text']} |")

    slash_table = ["| Command | Description |", "|---|---|"]
    for item in slash:
        arg = f" {item['argument_hint']}" if item["argument_hint"] else ""
        slash_table.append(f"| `/{item['id']}{arg}` | {item['description']} |")

    agent_table = ["| Agent | Purpose |", "|---|---|"]
    for item in agents:
        agent_table.append(f"| `{item['id']}` | {item['description']} |")

    replacements = {
        "<!-- BEGIN GENERATED_MODEL_SKILLS -->": "\n".join(model_table),
        "<!-- BEGIN GENERATED_SLASH_SKILLS -->": "\n".join(slash_table),
        "<!-- BEGIN GENERATED_AGENTS -->": "\n".join(agent_table),
    }
    for marker, table in replacements.items():
        start = text.index(marker)
        end_marker = marker.replace("BEGIN", "END")
        end = text.index(end_marker)
        text = text[: start + len(marker)] + "\n" + table + "\n" + text[end:]
    PLUGIN_README.write_text(text)


def main() -> None:
    skills = load_skill_docs()
    agents = load_agent_docs()
    DATA_MODULE.write_text(build_data_module(skills, agents))
    sync_root_skill(skills)
    sync_top_level_skill_catalog(skills)
    sync_readme(skills, agents)
    print(f"Generated catalog for {len(skills)} skills and {len(agents)} agents.")


if __name__ == "__main__":
    main()
