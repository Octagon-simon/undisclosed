# Curated skill catalog

**Problem.** Every bundled example skill ships inside the app and is auto-installed
into the user's skill store at startup. That is fine for a dozen tiny prompt-only
skills, but the catalog now includes asset-heavy ones (audio beds, fonts, textures,
video). Shipping and pre-installing all of them bloats the app and floods every
user's skill list with things they will never use. The user gets no say in what is
installed.

**Solution (planned).** Present skills as a curated, browsable catalog: each entry
shows enough to decide (name, one-line description, tags, size, installed?). Nothing
is installed until the user asks. Each not-yet-installed entry gets an **Import**
button; clicking it opens a new chat seeded with a prompt that has the agent install
that skill into the user's skills.

**Status:** not implemented. This doc records the goal so the current bundled-sync
behavior (below) is replaced deliberately, not by accident.

---

## Current behavior (what we have today)

- `resources/example-skills/` holds **12 bundled skills, ~3 MB total** (frontend,
  UI, design, and skill-authoring). The video/media skills that used to sit here are
  **no longer shipped, auto-installed, or vendored**: they live in their upstream
  GitHub projects and install on demand - see `docs/extra-skills.md`.
- At startup `skill_service.sync_example_skills()` copies **every** example into
  `~/.undisclosed/skills/` and writes a `.undisclosed-example-skill` marker per
  directory. `skills_scan` then reports each with `isExample: true`, and
  `skill_config_init()` backfills `isExample` for matching config entries.
- The UI groups them under an **Examples** section (`AgentSkills.tsx`; the full page
  is `pages/Agents/Skills.tsx` + `SkillListItem.tsx`) with an enable toggle. There is
  **no import step**: they are already installed.
- Packaging: electron-builder `extraResources` ships `resources/example-skills` to
  `<resources>/example-skills`; `brain-launcher.ts` points
  `UNDISCLOSED_EXAMPLE_SKILLS_DIR` at it.

### Sizes (the reason this matters)

The **bundled** tree is now ~3 MB; the largest entry is `uipro` at 1.7 MB.
The asset-heavy video/media skills were removed from the repo entirely (they were
~34 MB, dominated by `brag` at 16 MB - about 12 MB of mp3 beds - plus
`music-to-video` 6.3 MB, `embedded-captions` 3.6 MB, and `media-use` 2.0 MB).
They now install on demand from upstream GitHub - see `docs/extra-skills.md`.

## Goal

1. A single curated catalog of skills users can browse.
2. Users install only what they want; the app does not pre-install the rest.
3. A catalog entry is enough to decide: name, one-line description, optional
   category/tags, size, installed state.
4. Installing is a first-class flow: an **Import** button on the entry that opens a
   new chat and asks the agent to install that skill into the user's skills.

## Why not just bundle everything

- App size and the user's skill list grow together, while most users need a handful.
- Asset-heavy skills dominate the bytes (see sizes above).
- Some candidate skills cannot ship at all under their license (see guardrails), so a
  catalog that can point at sources is more future-proof than a vendored tree.

## Proposed shape (open)

- **Catalog source**: a manifest of `{name, description, tags, size, source, license}`,
  either bundled as metadata only or fetched from a remote registry. Keep it a list,
  not a vendored copy of every skill.
- **Entry states**: available / installing / installed / update-available.
- **Import flow**: button -> create chat -> seeded prompt -> the agent resolves the
  skill (bundled small files, or download from `source`) and installs it into
  `~/.undisclosed/skills/` **without** the example marker, so it lands under
  "Your skills".
- **Relationship to today's examples**: either (a) keep a small set pre-installed as
  true starter examples and catalog the heavy ones, or (b) move all examples to the
  catalog and pre-install nothing.
- **Local/dev copies**: a way to bulk-install the heavy skills into
  `~/.undisclosed/skills/` for the developer without shipping them to users.

## Licensing guardrails

- `feitangyuan/onetake` is **excluded**: PolyForm Noncommercial 1.0.0 forbids
  commercial use. Point users at the author's own license instead.
- Anthropic `docx` / `pptx` / `xlsx` are excluded for the same reason.
- `heygen-com/hyperframes` is **Apache-2.0** and is vendored (21 skills) with its
  `LICENSE` and `NOTICE.md` retained.
- The hyperframes skills bundle **GSAP 3.15** (GSAP Standard License, not OSI) in
  `talking-head-recut` and `music-to-video`.
- A `license` field per catalog entry makes these decisions explicit.

## Open questions

- Bundle the manifest, or fetch it? (Offline reliability vs freshness.)
- Does "install" always download, or reuse files already in the app? If the app ships
  the skill anyway, no bytes are saved, which argues for NOT vendoring heavy skills.
- Is there a size cap / cutoff for what is catalogued vs bundled? (Largest bundled
  skill today is 16 MB; there is no 100 MB skill.)
- Do catalog-installed skills update, and how are "Examples" vs "Yours" shown after
  install?

## Where it lives (current, for reference)

- Store/sync: `brain/app/service/skill_service.py` (`sync_example_skills`,
  `example_skills_metadata`, `is_example_skill_dir`)
- Config: `brain/app/service/skill_config_service.py`,
  `~/.undisclosed/user_<id>/skills-config.json`
- Import (existing): `skill_import_zip` in `brain/app/controller/skill_controller.py`
  and `skill_service.py`
- UI: `agent-ui/src/components/CodeAgentWorkspace/AgentSkills.tsx`,
  `agent-ui/src/pages/Agents/Skills.tsx`, `SkillListItem.tsx`
- Examples + packaging: `resources/example-skills/`, electron-builder `extraResources`,
  `UNDISCLOSED_EXAMPLE_SKILLS_DIR` in `brain-launcher.ts`
