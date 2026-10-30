# SkillSpector in the skill workflow

Status: proposed, nothing implemented.
Source: https://github.com/NVIDIA/SkillSpector (README fetched 2026-10-29, repo
`NVIDIA/SkillSpector`, package name `skillspector`, version 2.12.0).

## 1. What the tool actually is

Verified from the README and `pyproject.toml`, not from the pitch:

- Static-first security scanner for agent skills. Input can be a directory, a
  single `SKILL.md`, a git URL, a zip, or an MCP registry snapshot.
- 71 patterns across 17 categories (prompt injection, exfiltration, privilege
  escalation, supply chain, excessive agency, tool poisoning, dangerous code via
  AST, taint tracking, YARA signatures, and so on). Two stages: static pass, then
  an optional LLM pass.
- `--no-llm` gives a fully static scan and skips provider init entirely.
- Outputs `terminal | json | markdown | sarif`, `--format json -o -` to stdout.
- Exit codes are documented as a stable contract:
  - `0` scan done, `risk_score` <= 50 (SAFE or CAUTION)
  - `1` risk > 50, or a strict gate fired (`--fail-on-findings`,
    `--fail-on-incomplete`, `--min-coverage`)
  - `2` error: bad input, unreadable source, internal failure
- `--baseline FILE` suppresses known findings so rescans surface only new ones.
- `--recursive --max-skills N` scans a parent folder of skills independently.
- There is an MCP mode behind the `mcp` extra, and a Docker image.

Two hard constraints that shape everything below:

1. **Python >= 3.12,<3.16.** `brain/pyproject.toml` pins
   `requires-python = ">=3.11,<3.12"`. It cannot be a brain dependency.
2. **Heavy dependency tree.** `langgraph`, `langchain-*`, `boto3`,
   `yara-python`, `google-auth`, `openai>=2.25`. This is not something to vendor
   or audit-and-paste into our repo.

License is Apache-2.0, so shipping or calling it is fine. The packaged app does
not currently ship a second Python runtime, so that is a real cost decision, not
a legal one.

## 2. Where it fits our workflow

There are three places a skill enters this product, and they need different
treatment:

| Surface | Path | Trust | Gate |
| --- | --- | --- | --- |
| Bundled skills | `resources/example-skills/` (20 skills, shipped via `extraResources`) | Ours | Build/CI only. No runtime cost. |
| UI import | Electron IPC -> `skill_controller.py:148` -> `skill_import_zip()` at `skill_service.py:442` | Third party (zip the user picked) | Runtime gate, fail-closed |
| "Paste a URL" install | Agent fetches into `~/.undisclosed/skills/<name>/` (documented in `docs/extra-skills.md`) | Third party, arbitrary repo | Runtime gate, fail-closed |
| Skill authoring | `skill-creator` writes a new skill | Ours, but model-generated | Scan on save, warn only |

The URL path is the one that actually matters. It is the least controlled: the
agent writes files into the skills root directly, and nothing inspects them
before they become instructions the next agent turn will follow.

## 3. Architecture decision: call the CLI, do not import it

Recommendation: **subprocess against a standalone install, never a brain
dependency.**

- Dev/CI: `uv tool install git+https://github.com/NVIDIA/skillspector.git`.
  `uv` fetches its own 3.12 interpreter, so the brain's 3.11 pin is untouched.
- Runtime (v1): detect a `skillspector` binary on PATH (or
  `~/.local/bin/skillspector`). If absent, record the skill as `unscanned` and
  do not fake a verdict.
- Runtime (v2, only if we decide to ship it): bundle a sidecar venv and call it
  by absolute path. That is a second interpreter plus a few hundred megabytes in
  the installer. I have not measured the packaged size yet, and I would want a
  real number before committing to it.

Why not the MCP mode: an MCP tool is something the model chooses to call. An
install gate has to be an unconditional step in the install code path, not a
tool the model may skip. If we also want in-conversation scanning later, wiring
`skillspector[mcp]` into `brain/app/service/mcp_config.py` is a small additive
change on top of the same binary.

Why not in-process import: the 3.12 pin, plus importing `langgraph` and
`boto3` into a 3.11 brain process is not going to work and would bloat the
sidecar we already ship.

## 4. Policy

Not "run the scanner", but "what happens with the result". Proposed rules:

- Bundled skills (`resources/example-skills/`): CI job, exit code must be 0.
  Findings get triaged once, then committed as `.skillspector-baseline.yaml` so
  later PRs only fail on new findings. `--no-llm`, no API keys in CI.
- Imported skills: scan before the files land in `SKILLS_ROOT`. Wire it into
  `skill_import_zip()` after extraction into the temp dir, before step 3.
  - exit `1` with `risk_score` > 50, or any finding of severity HIGH/critical:
    **refuse the import**, return `{"success": False, "error": ..., "report":
    ...}` so the UI can show why.
  - CAUTION / low score: import, but stamp the verdict on the skill record.
  - exit `2`: **refuse**. A scanner that cannot read the skill tells us nothing,
    and "unknown" must not silently become "safe".
  - Scanner missing: allow, mark `unscanned`, and say so in the UI. Fail-open is
    a deliberate choice for v1 only because we do not ship the binary yet.
- Scan must have a hard timeout. A skill install should not hang on OSV.dev or a
  YARA file. Cap at ~30s, kill the child, treat as exit 2.

## 5. Privacy and network

This matters more here than for a normal dev tool, because the product's pitch
is local-first.

- `--no-llm` keeps skill *contents* local. That is the default and the only mode
  we should enable without explicit consent.
- SC4 (known-vulnerable dependencies) still calls `api.osv.dev` **even with
  `--no-llm`**, sending package names and versions, not file contents. There is
  no documented flag to disable just that lookup; offline mode degrades to a
  small bundled list.
- So the runtime gate needs a stated behavior: either we accept dependency
  coordinates going to OSV.dev and disclose it, or we run the scan with egress
  blocked and accept a weaker supply-chain check. I would default to the latter
  for installed skills and document the tradeoff. This is a product decision,
  not a technical one.
- The LLM stage stays off by default everywhere. If we ever expose it, it is a
  separate opt-in with an explicit "this uploads your skill's files" prompt.

## 6. Implementation, phased

**Phase 1: prove the scanner on our own skills (no product code).**
1. `uv tool install git+https://github.com/NVIDIA/skillspector.git`, confirm
   version and that `--no-llm` works offline-ish.
2. `skillspector scan resources/example-skills --recursive --max-skills 40
   --no-llm --format json -o /tmp/bundled.json`, read every finding against the
   actual skill text, decide true vs false positive, write
   `.skillspector-baseline.yaml`.
3. Only then decide whether the runtime gate is worth building. If the bundled
   set, which we wrote ourselves, throws dozens of findings, the signal-to-noise
   on third-party skills is going to be poor and the policy needs a severity
   filter before it can block anything.

**Phase 2: CI gate on bundled skills.**
- New job in `.github/workflows/tests.yml` (or a small `skills.yml`). Ubuntu,
  `uv tool install`, `--no-llm --baseline .skillspector-baseline.yaml`, upload
  the SARIF/JSON as an artifact. Blocks on exit 1.
- Keep it a separate job from `pytest`, so a scanner outage does not red the
  test suite.

**Phase 3: runtime gate on import.**
- New module `brain/app/service/skill_scan_service.py`:
  `scan_skill_dir(path) -> ScanResult` (status, score, severity, findings,
  scanner_version, duration), subprocess with timeout, JSON parse, no exceptions
  escaping into the import path.
- Call it from `skill_import_zip()` between extraction and the conflict check, so
  a rejected skill never touches `SKILLS_ROOT`.
- Store the report at `~/.undisclosed/skills/<name>/.skillspector/report.json`
  and expose score/severity through `skills_scan()` so the Skills screen can
  show a badge. Keep it out of the model's context: this is metadata, not a
  prompt.
- Tests: mock the subprocess for the four exit-code cases plus timeout plus
  missing binary.

**Phase 4: cover the URL path.**
- The URL install is the agent writing files directly, so a service-level gate
  does not see it. Options: a post-write check in the skills scan that flags
  unscanned skills and prompts; or a dedicated `skill_install_from_url` brain
  tool that downloads, scans, then commits to `SKILLS_ROOT`. The second is the
  honest fix and is where I would spend the effort, but it touches the tool
  surface and the system prompt.

**Phase 5: docs.**
- `docs/extra-skills.md`: add a "this gets scanned" note for the URL flow.
- A short `docs/skills-security.md`: what the scanner checks, what `unscanned`
  means, and the OSV.dev egress disclosure.

## 7. Risks and honest limits

- **Detection quality.** NVIDIA's own numbers: 26.1% of 31,132 skills have
  vulnerabilities, 5.2% look malicious. That is a corpus where most findings are
  low-signal. Prompt-injection rules in particular will flag legitimate skills
  that say "always follow the user's request" or quote attacker text in a doc.
  Expect a triage pass and a severity threshold before this can block anything.
- **Pattern-based, so bypassable.** Obfuscated or multi-stage payloads will slip
  through the static pass. This is a seatbelt, not a sandbox.
- **Tool maturity.** Classifier says `Development Status :: 3 - Alpha`, but the
  CLI exit-code and JSON contracts are explicitly documented as stable, which is
  what we depend on.
- **Supply chain of the scanner.** It pulls `yara-python` (native) and a lot of
  LangChain. Pinning a commit SHA rather than tracking `main` is the right call
  for CI.
- **Baseline drift.** Fingerprint baselines are evidence-bound; editing a
  baselined skill invalidates its suppression and the finding comes back. That
  is correct behavior, but it means every bundled-skill edit may need a baseline
  refresh. Glob rules are the escape hatch.

## 8. Decisions I need from you

1. v1 scope: CI-only on bundled skills (Phase 1-2), or also the runtime import
   gate (Phase 3)?
2. Ship the scanner inside the app (sidecar, second Python, larger installer) or
   keep it an opt-in external binary with `unscanned` as the default for users
   who do not have it?
3. OSV.dev egress during a scan: accept and disclose, or block network and take
   the weaker supply-chain check?
4. Blocking policy: refuse any HIGH finding, or refuse only on `risk_score` > 50
   and downgrade the rest to warnings?

My default if you just say "go": Phase 1 + 2 first, fail-closed import gate as
Phase 3 with `unscanned` when the binary is absent, block only on score > 50 or a
HIGH finding, and no bundled sidecar.
