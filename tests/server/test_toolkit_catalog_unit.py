from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_MODULE = ROOT / "src" / "mcp_stata" / "toolkit_catalog_data.py"
SERVER_FILE = ROOT / "src" / "mcp_stata" / "server.py"
PLUGIN_SKILLS = ROOT / "plugin" / "skills"
PYPROJECT = ROOT / "pyproject.toml"


def _load_data_module():
    spec = importlib.util.spec_from_file_location("toolkit_catalog_data", DATA_MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_catalog_contains_researcher_skills():
    mod = _load_data_module()
    ids = {item["id"] for item in mod.SKILLS}
    assert "stata-replication" in ids
    assert "stata-data-audit" in ids
    assert "stata-publication-qa" in ids
    assert "stata-environment-diagnose" in ids


def test_catalog_metadata_shape():
    mod = _load_data_module()
    replication = mod.SKILL_BY_ID["stata-replication"]
    assert replication["invocation_type"] == "context-skill"
    assert "supported_agents" in replication
    assert "trigger_text" in replication
    assert "content" in replication
    assert any(item["id"] == "replicate_result" for item in mod.PROMPTS)
    assert any(item["uri"] == "stata://project/manifest" for item in mod.RESOURCES)


def test_server_uses_generated_catalog():
    text = SERVER_FILE.read_text()
    assert "from .toolkit_catalog_data import SKILLS, SKILL_BY_ID" in text
    assert '"resource_uri": f"stata://skills/{item[\'id\']}"' in text
    assert 'return doc["content"]' in text


def test_skill_frontmatter_is_minimal():
    for path in PLUGIN_SKILLS.glob("*/SKILL.md"):
        text = path.read_text()
        frontmatter = text.split("---\n", 2)[1]
        keys = {
            line.split(":", 1)[0].strip()
            for line in frontmatter.splitlines()
            if ":" in line and line.strip()
        }
        assert keys == {"name", "description"}, f"{path} has unexpected frontmatter keys: {keys}"


def test_manifests_and_generated_openai_yaml_exist():
    for skill_dir in PLUGIN_SKILLS.iterdir():
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            continue
        assert (skill_dir / "manifest.json").exists(), f"missing manifest for {skill_dir.name}"
        assert (skill_dir / "agents" / "openai.yaml").exists(), f"missing openai.yaml for {skill_dir.name}"


def test_catalog_references_and_scripts_resolve():
    mod = _load_data_module()
    for item in mod.SKILLS:
        skill_dir = ROOT / "plugin" / "skills" / item["id"]
        for ref in item.get("references", []):
            assert (skill_dir / ref).exists(), f"missing reference {ref} for {item['id']}"
        for script in item.get("scripts", []):
            assert (skill_dir / script).exists(), f"missing script {script} for {item['id']}"


def test_pyproject_force_includes_plugin_skills():
    text = PYPROJECT.read_text()
    for slug in (
        "modernize",
        "data-audit",
        "environment-diagnose",
        "publication-qa",
        "replication",
        "causal-inference",
        "table-builder",
        "power-analysis",
        "data-provenance",
        "referee-response",
    ):
        assert f"plugin/skills/stata-{slug}/SKILL.md" in text
