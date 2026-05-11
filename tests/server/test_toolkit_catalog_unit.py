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
    text = SERVER_FILE.read_text(encoding="utf-8")
    assert "from .toolkit_catalog_data import SKILLS, SKILL_BY_ID, CHECKLISTS" in text
    assert '"resource_uri": f"stata://skills/{item[\'id\']}"' in text
    assert 'return doc["content"]' in text


def test_catalog_contains_checklists():
    mod = _load_data_module()
    assert len(mod.CHECKLISTS) > 0
    # Check for a few expected keys
    assert "data-audit" in mod.CHECKLISTS
    assert "stata-data-audit" in mod.CHECKLISTS
    assert "publication-qa" in mod.CHECKLISTS
    assert "# Data Audit Checklist" in mod.CHECKLISTS["data-audit"]


def test_skill_frontmatter_is_minimal():
    for path in PLUGIN_SKILLS.glob("*/SKILL.md"):
        text = path.read_text(encoding="utf-8")
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


def test_catalog_is_complete_and_synced():
    """Verifies that the generated catalog is a 1:1 match with the plugin/skills directory."""
    mod = _load_data_module()
    
    # Get all skill directories that should be in the catalog
    expected_skill_ids = set()
    for skill_dir in PLUGIN_SKILLS.iterdir():
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            # The skill ID comes from the 'name' field in frontmatter, 
            # which by convention matches the directory name for these skills
            expected_skill_ids.add(skill_dir.name)
            
    actual_skill_ids = {item["id"] for item in mod.SKILLS}
    
    # Check for missing or extra skills
    missing = expected_skill_ids - actual_skill_ids
    extra = actual_skill_ids - expected_skill_ids
    
    assert not missing, f"Skills in plugin/skills but missing from catalog: {missing}"
    # Note: Extra skills are allowed if they come from other sources, 
    # but currently we expect a 1:1 match with plugin/skills.
    assert not extra, f"Skills in catalog but missing from plugin/skills: {extra}"

    # Verify content embedding for each skill
    for skill_id in expected_skill_ids:
        skill_dir = PLUGIN_SKILLS / skill_id
        skill_data = mod.SKILL_BY_ID[skill_id]
        
        # Check basic fields
        assert skill_data["name"] == skill_id
        assert "description" in skill_data
        assert "content" in skill_data
        
        # Check reference embedding
        manifest_path = skill_dir / "manifest.json"
        if manifest_path.exists():
            import json
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_refs = manifest.get("references", [])
            
            for ref in expected_refs:
                assert ref in skill_data["reference_docs"], f"Missing embedded reference {ref} for {skill_id}"
                ref_content = (skill_dir / ref).read_text(encoding="utf-8")
                assert skill_data["reference_docs"][ref] == ref_content, f"Content mismatch for reference {ref} in {skill_id}"


def test_pyproject_contains_no_stale_force_includes():
    """Ensures we didn't leave any skill-related force-includes in pyproject.toml."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "plugin/skills/" not in text or "force-include" not in text.split("plugin/skills/")[0]
    assert "mcp_stata/skills-catalog" not in text
