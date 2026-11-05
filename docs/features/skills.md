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
- Bundled examples: `resources/example-skills/` (frontend/design/authoring, shipped
  and auto-installed). `refactoring-ui` is the design-rules skill (`SKILL.md` +
  `references/diagnose.md`, `references/systems.md`, `references/techniques.md`, and
  `assets/tokens.css`, MIT). `reverse-engineer-anything` (`SKILL.md` + six
  `references/*.md`, MIT, vendored from github.com/morluto/rea) covers binaries,
  Electron/JavaScript, Android and runtime evidence. It ships instructions only,
  so its tools need REA's MCP server in `~/.undisclosed/mcp.json`
  (`npx -y rea-agents@latest mcp`); it is bundled but **off by default**, and
  each user enables it after registering that server through Connectors -> Add
  custom -> Local. The skill's own setup section spells that out, because
  `rea setup` has no target for this client. Without the server the skill's
  recovery path falls back to the `npx` CLI. Extra skills (video/media/motion) are no longer vendored;
  they live in their upstream GitHub projects and install on demand - see
  `docs/extra-skills.md`.
- Packaging: the examples ship via electron-builder `extraResources` to
  `<resources>/example-skills`. The frozen brain can't resolve that path from
  `__file__` (PyInstaller extracts to a temp dir), so `brain-launcher.ts` points
  it there explicitly with `UNDISCLOSED_EXAMPLE_SKILLS_DIR`.

## UI skill composition

Applying a UI/design skill is not the last step, and the user never has to ask
for a design pass. The brain prompt (`SINGLE_AGENT_SYS_PROMPT` and the other
`Skills System` blocks in `brain/app/agent/prompt.py`) carries a frontend/UI
gate: any task that touches frontend code or UI/UX at all - components, pages,
styles, layout, design tokens, user-facing copy, or a flow the user will see -
must load `refactoring-ui` before building, not after, and run its diagnose pass
over the whole flow it touched before declaring the task done. The pass is not
desktop-only: the same flow is rendered at 320, 375 and 414 CSS px and diagnosed
as its own layout (no horizontal scroll, one column below ~640px, 44px tap
targets, 16px inputs, overlays clamped inside the viewport, safe-area padding,
no hover-only actions), because a clean desktop review is half the job. Findings
are fixed in the same task: ad-hoc spacing/type/color off the scale, weak
hierarchy, flat depth, contrast, and user-facing strings left hardcoded where
the project has copy or design tokens. The gate stacks with any other UI skill the user
enabled (`premium-frontend-ui`, `uipro`, `ui-styling`, `banner-design`,
`design-system`, a taste/design skill) and never replaces it.

`refactoring-ui` ships in `resources/example-skills/`, is auto-synced into
`~/.undisclosed/skills/`, and is enabled by default for every user
(`DEFAULT_ENABLED_EXAMPLE_SKILLS` in `skill_config_service.py`). If a user
disables it, `load_skill` fails and the prompt requires the agent to say which
checks it could not run rather than claim a pass it did not do.

`SINGLE_AGENT_SYS_PROMPT` also has a dedicated `<frontend_ui_work>` section
(load, scope the flow, desktop diagnose, mobile pass, fix, report if blocked) and
the pass is step 4 of its `<verification_workflow>`, so the typecheck, tests and
review run on the corrected UI. The trigger lives in the prompt, not in each
skill's `SKILL.md`, so it stays in one place and covers every UI skill the user
enables. The concrete small-screen checklist (overflow, tap targets, input
sizing, overlay clamping, safe areas, hover-only actions) lives in
`resources/example-skills/refactoring-ui/SKILL.md` under
"Mobile and responsive", so the agent reads it every time it loads the skill.

## See also

- `docs/features/curated-skill-catalog.md` - the planned browse-and-install catalog,
  so the app stops bundling and pre-installing every example skill.
- `docs/extra-skills.md` - the extra (video/media) skills, their upstream GitHub
  projects, and how to install one on demand.
