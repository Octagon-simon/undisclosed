# Skills

**Problem.** A general agent needs task-specific know-how (how to produce a deck,
how to run a particular workflow) without hardcoding it or fine-tuning a model.
Users also want to bring their own.

**Solution.** A skill system: skills are folders with a `SKILL.md` the agent can
load, plus optional scripts and references. They are listed, toggled, imported,
and used like tools.

---

## Skill layout

A skill is a directory containing at minimum a `SKILL.md`, and typically
`scripts/` and `references/`. The bundled example is
`resources/example-skills/skill-creator/`:

```
skill-creator/
  SKILL.md
  references/output-patterns.md, workflows.md
  scripts/init_skill.py, package_skill.py, quick_validate.py
```

`skill-creator` is itself a skill for building skills: `init_skill.py` scaffolds a
new skill folder, `package_skill.py` bundles it, and `quick_validate.py` checks it.

## How the agent uses one

- **Attach in the composer**: the user attaches a skill from the chatbox (a
  `#skill-name` pill). The skill tools are registered as **core** in tool-RAG
  (`"skill"` marker in `_CORE_TOOLKIT_MARKERS`), so the agent can load an attached
  skill this turn instead of the router filtering it out.
- **Load**: the `SkillToolkit` (`brain/app/agent/toolkit/skill_toolkit.py`) reads
  skill roots, merges the user's skill config, and exposes the skill's `SKILL.md`
  content (and its files) to the agent.
- **The UI lists skills** from the brain, so the picker is never empty even in the
  embed (`AgentSkills.tsx`, and `PickerPanel` loads skills when its picker opens).

## Management (backend)

`brain/app/controller/skill_controller.py` + `brain/app/service/skill_service.py`
and `skill_config_service.py` expose:

- `GET /skills/config`, `POST /skills/config/init`, `PUT /skills/config/{name}`:
  per-user enable/disable and per-agent allow-lists.
- scan / list files / read / write / delete.
- **`skill_import_zip`**: add a skill by uploading a `SKILL.md` zip.

`_get_merged_skill_config` merges a default config with the user's, and
`_is_skill_enabled` / `_is_agent_allowed` decide whether a skill applies to a
given agent. Roots are resolved with a user-scoped and a global/example scope
(`_skill_roots`), so bundled examples and user skills coexist.

## The UI

`agent-ui/src/components/CodeAgentWorkspace/AgentSkills.tsx` (a compact,
panel-native screen) syncs from disk, lists "Your skills" + "Examples" with an
enable toggle and delete, and adds a skill via zip upload. (A device symlink
`~/.undisclosed/skills` backs the local skill store.)

## Where it lives

- Toolkit: `brain/app/agent/toolkit/skill_toolkit.py`
- Backend: `brain/app/controller/skill_controller.py`, `brain/app/service/skill_service.py`, `skill_config_service.py`
- UI: `agent-ui/src/components/CodeAgentWorkspace/AgentSkills.tsx`, `ChatBox/BottomBox/PickerPanel.tsx`
- Examples: `resources/example-skills/skill-creator/`
