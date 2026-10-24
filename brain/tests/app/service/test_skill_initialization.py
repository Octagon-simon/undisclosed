# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

import json
from pathlib import Path

import pytest
import yaml

from app.agent.toolkit import skill_toolkit as agent_skill_toolkit
from app.service import skill_config_service, skill_service

pytestmark = pytest.mark.unit

BUNDLED_SKILLS_ROOT = (
    Path(__file__).resolve().parents[4] / "resources" / "example-skills"
)


def write_skill(
    root,
    folder_name,
    name,
    description="Example skill",
    body="Use this skill.",
):
    skill_dir = root / folder_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f'description: "{description}"',
                "---",
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )
    return skill_dir


def test_skills_scan_seeds_and_marks_example_skills(tmp_path, monkeypatch):
    example_root = tmp_path / "bundled" / "example-skills"
    skills_root = tmp_path / "home" / ".undisclosed" / "skills"
    write_skill(example_root, "pdf", "pdf")
    write_skill(skills_root, "custom", "Custom")

    monkeypatch.setenv(skill_service.EXAMPLE_SKILLS_ENV, str(example_root))
    monkeypatch.setattr(skill_service, "SKILLS_ROOT", skills_root)

    skills = skill_service.skills_scan()

    by_name = {skill["name"]: skill for skill in skills}
    assert (skills_root / "pdf" / "SKILL.md").exists()
    assert by_name["pdf"]["isExample"] is True
    assert by_name["Custom"]["isExample"] is False


def test_skills_scan_updates_existing_example_skills(tmp_path, monkeypatch):
    example_root = tmp_path / "bundled" / "example-skills"
    skills_root = tmp_path / "home" / ".undisclosed" / "skills"
    write_skill(example_root, "pdf", "pdf", body="New bundled content")
    existing_dir = write_skill(
        skills_root, "pdf", "pdf", body="Old bundled content"
    )
    (existing_dir / "stale.txt").write_text("remove me", encoding="utf-8")

    monkeypatch.setenv(skill_service.EXAMPLE_SKILLS_ENV, str(example_root))
    monkeypatch.setattr(skill_service, "SKILLS_ROOT", skills_root)

    skill_service.skills_scan()

    updated_content = (skills_root / "pdf" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "New bundled content" in updated_content
    assert not (skills_root / "pdf" / "stale.txt").exists()
    assert (skills_root / "pdf" / skill_service.EXAMPLE_SKILL_MARKER).exists()


def test_skills_scan_survives_example_sync_failure(tmp_path, monkeypatch):
    skills_root = tmp_path / "home" / ".undisclosed" / "skills"
    write_skill(skills_root, "custom", "Custom")

    def boom():
        raise PermissionError("read-only skills dir")

    monkeypatch.setattr(skill_service, "sync_example_skills", boom)
    monkeypatch.setattr(skill_service, "SKILLS_ROOT", skills_root)

    skills = skill_service.skills_scan()

    assert [skill["name"] for skill in skills] == ["Custom"]


def test_frozen_brain_finds_examples_next_to_executable(
    tmp_path, monkeypatch
):
    bundle = tmp_path / "Resources" / "example-skills"
    bundle.mkdir(parents=True)
    executable = tmp_path / "Resources" / "brain" / "undisclosed-brain"

    monkeypatch.delenv(skill_service.EXAMPLE_SKILLS_ENV, raising=False)
    monkeypatch.setattr(skill_service.sys, "frozen", True, raising=False)
    monkeypatch.setattr(skill_service.sys, "executable", str(executable))

    roots = skill_service._candidate_example_skill_roots()

    assert bundle in roots
    assert skill_service.get_example_skills_root() == bundle


def test_skill_config_init_registers_bundled_example_skills(
    tmp_path, monkeypatch
):
    example_root = tmp_path / "bundled" / "example-skills"
    example_root.mkdir(parents=True)
    (example_root / "default-config.json").write_text(
        json.dumps({"version": 1, "skills": {}}),
        encoding="utf-8",
    )
    write_skill(example_root, "docx", "docx")
    write_skill(example_root, "antislop", "antislop")

    eigent_root = tmp_path / "home" / ".undisclosed"
    monkeypatch.setenv(skill_service.EXAMPLE_SKILLS_ENV, str(example_root))
    monkeypatch.setattr(skill_config_service, "UNDISCLOSED_ROOT", eigent_root)

    config = skill_config_service.skill_config_init("new_user")

    # A curated set starts enabled; the rest are registered but off.
    assert config["skills"]["antislop"]["enabled"] is True
    assert config["skills"]["docx"]["enabled"] is False
    assert config["skills"]["docx"]["scope"] == {
        "isGlobal": True,
        "selectedAgents": [],
    }
    assert config["skills"]["docx"]["isExample"] is True

    persisted = json.loads(
        (eigent_root / "user_new_user" / "skills-config.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["skills"]["docx"]["isExample"] is True
    assert persisted["skills"]["docx"]["enabled"] is False


def test_skill_config_load_migrates_legacy_email_config(tmp_path, monkeypatch):
    eigent_root = tmp_path / "home" / ".undisclosed"
    legacy_dir = eigent_root / "alice"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "skills-config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "skills": {
                    "pdf": {
                        "enabled": False,
                        "scope": {"isGlobal": True, "selectedAgents": []},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_config_service, "UNDISCLOSED_ROOT", eigent_root)

    config = skill_config_service.skill_config_load(
        "user_42", legacy_user_id="alice@example.com"
    )

    assert config["skills"]["pdf"]["enabled"] is False
    assert not (legacy_dir / "skills-config.json").exists()
    assert (eigent_root / "user_42" / "skills-config.json").exists()


def test_skill_config_migration_merges_without_overwriting_new_config(
    tmp_path, monkeypatch
):
    eigent_root = tmp_path / "home" / ".undisclosed"
    legacy_dir = eigent_root / "alice"
    user_dir = eigent_root / "user_42"
    legacy_dir.mkdir(parents=True)
    user_dir.mkdir(parents=True)
    (legacy_dir / "skills-config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "skills": {
                    "pdf": {"enabled": False},
                    "docx": {"enabled": True},
                },
            }
        ),
        encoding="utf-8",
    )
    (user_dir / "skills-config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "skills": {
                    "pdf": {"enabled": True},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_config_service, "UNDISCLOSED_ROOT", eigent_root)

    config = skill_config_service.skill_config_load(42, legacy_user_id="alice")

    assert config["skills"]["pdf"]["enabled"] is True
    assert config["skills"]["docx"]["enabled"] is True
    assert not (legacy_dir / "skills-config.json").exists()


def test_agent_skill_toolkit_reads_canonical_user_config_path(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(agent_skill_toolkit.Path, "home", lambda: tmp_path)

    assert agent_skill_toolkit._get_user_config_path("42") == (
        tmp_path / ".undisclosed" / "user_42" / "skills-config.json"
    )
    assert agent_skill_toolkit._get_user_config_path("user_42") == (
        tmp_path / ".undisclosed" / "user_42" / "skills-config.json"
    )


def test_skill_toolkit_allows_single_agent_aliases():
    config = {
        "demo": {
            "enabled": True,
            "scope": {
                "isGlobal": False,
                "selectedAgents": ["single_agent"],
            },
        }
    }
    assert agent_skill_toolkit._is_agent_allowed(
        "demo", "single_agent", config
    )
    assert agent_skill_toolkit._is_agent_allowed(
        "demo", "Agents.single_agent", config
    )
    assert not agent_skill_toolkit._is_agent_allowed(
        "demo", "foo.single_agent", config
    )
    assert not agent_skill_toolkit._is_agent_allowed(
        "demo", "developer_agent", config
    )


def test_skill_toolkit_normalizes_selected_single_agent_aliases():
    config = {
        "demo": {
            "enabled": True,
            "scope": {
                "isGlobal": False,
                "selectedAgents": ["Agents.single_agent"],
            },
        }
    }
    assert agent_skill_toolkit._is_agent_allowed(
        "demo", "single_agent", config
    )


def test_parse_skill_frontmatter_keeps_inline_description():
    content = "\n".join(
        [
            "---",
            "name: plain",
            'description: "A single-line description."',
            "---",
            "",
            "Body.",
        ]
    )
    assert skill_service._parse_skill_frontmatter(content) == {
        "name": "plain",
        "description": "A single-line description.",
    }


def test_parse_skill_frontmatter_reads_folded_block_description():
    content = "\n".join(
        [
            "---",
            "name: hyperframes",
            "description: >",
            "  Mandatory entry point: read this first for any request to make,",
            "  create, edit, animate, or render a video.",
            "---",
            "",
            "Body.",
        ]
    )
    assert skill_service._parse_skill_frontmatter(content) == {
        "name": "hyperframes",
        "description": (
            "Mandatory entry point: read this first for any request to make, "
            "create, edit, animate, or render a video."
        ),
    }


def test_parse_skill_frontmatter_reads_literal_block_description():
    content = "\n".join(
        [
            "---",
            "name: literal",
            "description: |",
            "  line one",
            "  line two",
            "---",
        ]
    )
    assert skill_service._parse_skill_frontmatter(content) == {
        "name": "literal",
        "description": "line one\nline two",
    }


def test_parse_skill_frontmatter_block_scalar_stops_at_dedent():
    # The folded block must end at the next dedented key, not swallow it.
    content = "\n".join(
        [
            "---",
            "name: dedent",
            "description: >",
            "  first line",
            "",
            "  second line",
            "tags: [a, b]",
            "---",
        ]
    )
    assert skill_service._parse_skill_frontmatter(content) == {
        "name": "dedent",
        "description": "first line second line",
    }


def test_parse_skill_frontmatter_returns_none_without_description():
    content = "\n".join(["---", "name: only-name", "---"])
    assert skill_service._parse_skill_frontmatter(content) is None


def test_bundled_skill_frontmatter_parses_as_yaml():
    # CAMEL rejects a skill whose frontmatter is invalid YAML, so an unquoted
    # colon in a description silently makes the skill unloadable.
    assert BUNDLED_SKILLS_ROOT.is_dir()
    broken = []
    for skill_md in sorted(BUNDLED_SKILLS_ROOT.glob("*/SKILL.md")):
        frontmatter = skill_md.read_text(encoding="utf-8").split("---", 2)[1]
        try:
            meta = yaml.safe_load(frontmatter)
        except yaml.YAMLError as exc:
            broken.append(f"{skill_md.parent.name}: {exc}")
            continue
        if not isinstance(meta, dict) or not all(
            isinstance(meta.get(key), str) for key in ("name", "description")
        ):
            broken.append(f"{skill_md.parent.name}: missing name or description")
    assert broken == []


def test_bundled_reverse_engineer_skill_ships_enabled():
    assert (
        BUNDLED_SKILLS_ROOT / "reverse-engineer-anything" / "SKILL.md"
    ).is_file()
    assert (
        "reverse-engineer-anything"
        in skill_config_service.DEFAULT_ENABLED_EXAMPLE_SKILLS
    )
