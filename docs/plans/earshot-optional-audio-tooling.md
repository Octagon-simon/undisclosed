# Earshot: optional audio and video QA tooling

**Status: evaluated 2026-10-23, not adopted.** Nothing here is installed, wired, or
shipped. This page exists so the decision and the trial recipe survive the
conversation that produced them. Revisit it if audio or video work becomes a real
part of the product.

Upstream: **https://github.com/Leonxlnx/earshot** (MIT, `earshot` 0.4.0 alpha,
created 2026-10-15, ~2.4k stars on 2026-10-23).

---

## The gap it would fill

Our agent can *read* audio only as speech. `brain/app/agent/toolkit/audio_analysis_toolkit.py`
wraps CAMEL's `AudioAnalysisToolkit` with `OpenAIAudioModels`: transcribe speech,
answer a question about what was said. That is it.

It is also narrow in who gets it. `brain/app/agent/factory/multi_modal.py:165-186`
registers the toolkit **only** for the multi-modal agent, and only when
`model_platform` is OpenAI *and* the run is not on subscription auth. Every other
agent has no audio tool at all.

Meanwhile the media skills in [extra-skills.md](../extra-skills.md) (HyperFrames,
`media-use`, `hyperframes-audio`, `music-to-video`, `product-launch-video`) can
*source, assemble and mix* a soundtrack. Nothing in the stack can measure the
finished result: loudness against a target, whether the hit lands on the cut,
whether the "whoosh" actually reads as a whoosh, whether a fake sound passes as
recorded.

That is exactly the hole earshot fills, and it is the QA loop after a HyperFrames
render, not a replacement for those skills.

## What earshot actually does

A local, CPU-only Python tool plus an MCP server. The verbs that matter to us:

| Command | What it answers |
| --- | --- |
| `describe FILE` | What is this sound, with calibrated tags plus the closest alternative readings. |
| `match` / `rank` | Does this sound fit a description, and which candidate fits best. |
| `find FILE "a single key press"` | Where in a long recording the described moment happens. |
| `compare` / `ab` | Two takes against each other. |
| `realness` | Recorded or synthesized. |
| `timeline FILE --video V` | Events with time and level, sections, loudness, beat grid, and whether sound lands on picture cuts. |
| `critique` | A scorecard against professional launch films. |
| `measure FILE` | Objective numbers only: LUFS, true peak, LRA, envelope, spectrum, tempo, key. No models, so it is instant. |
| `sfx render ID -o x.wav` | A sound from the shipped 252-sound bank, aimed at a moment (`--dur`, `--apex`, `--pitch`). No models. |
| `kit render` | One bank sound per role, placed against a music bed and the cut. No models. |
| `mcp` | The same tools as an MCP server, models stay warm. |

`earshot doctor [--load]` checks the install, model cache, data files and CPU
threading.

**These numbers are the author's**, from the README and changelog. I read the
repo but never installed or ran it, so none of the quality claims are verified
here.

## Why it already fits our extension points

No product work is required to try it:

- **Skills.** `SkillToolkit` discovers `<workspace>/skills`, `<workspace>/.undisclosed/skills`,
  and `~/.undisclosed/skills` (`brain/app/agent/toolkit/skill_toolkit.py`, class
  docstring). Earshot ships two Claude-format skills, `skills/earshot` and
  `skills/real-sound`, in the same format, so they should load unchanged.
- **MCP.** Local servers live in `~/.undisclosed/mcp.json` and are merged into
  the agent config by `toolkit_assembler.py`; the Settings connector screen can
  paste raw JSON. See [connectors-and-mcp.md](../features/connectors-and-mcp.md).

So this is a user-level opt-in today, and a "detect it, offer to install it"
capability later, with no new transport or packaging work.

## Why it must not be a dependency

1. **Weight.** `torch>=2.6`, `transformers`, `librosa`, `scikit-learn`,
   `matplotlib`, plus ~1.1 GB of model downloads (LAION CLAP for text-audio
   embeddings, an AudioSet tagger) on first model use. `scripts/build-brain.sh`
   freezes the brain into one PyInstaller binary; this would balloon the
   installer and slow startup for every user, including the majority with no
   audio task.
2. **System dependency.** `ffmpeg` and `ffprobe` must be on `PATH`. Most editor
   users do not have them.
3. **Cold start.** Every CLI call is a new process and reloads the models
   (20-40 s). The MCP server keeps them warm, but our connect timeout is 20 s
   headless / 90 s desktop (`brain/app/agent/tools.py:189-197`,
   `MCP_CONNECT_TIMEOUT_HEADLESS` / `MCP_CONNECT_TIMEOUT`). The first audio call
   can look hung and get the server dropped for the turn.
4. **Maturity.** 0.4.0 alpha, eight days old, one author. The star count is a
   launch spike, not a track record. Expect breaking changes.
5. **Demand is narrow.** Most coding sessions contain no audio. A default tool
   would cost context in every turn and never fire.

## How to try it (when someone actually needs it)

Keep it out of the brain venv; torch conflicts are not worth debugging.

```bash
git clone https://github.com/Leonxlnx/earshot
cd earshot
python -m venv .venv
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -e ".[mcp]"
.venv/bin/python -m earshot doctor --load     # first model run downloads ~1.1 GB
```

Then, either:

- **As an MCP server**: Settings > Connectors > Paste JSON, into `~/.undisclosed/mcp.json`:

  ```json
  {
    "mcpServers": {
      "earshot": {
        "command": "/absolute/path/to/earshot/.venv/bin/python",
        "args": ["-m", "earshot", "mcp"],
        "env": { "EARSHOT_THREADS": "3" }
      }
    }
  }
  ```

  Restart the brain afterwards so the config is re-read.

- **As a skill**: paste
  `https://github.com/Leonxlnx/earshot/tree/main/skills/earshot` (and
  `.../skills/real-sound`) into chat and ask the agent to install it. The skill is
  only instructions; the CLI and MCP server above are what actually do the work.

## The two experiments that would settle it

Do these before writing any product code:

1. `earshot critique` against one of our real demo videos (the `brag` /
   HyperFrames output), and check whether its notes match what a person hears.
2. `earshot sfx render` a handful of UI clicks, pops and whooshes for the panel,
   and A/B them against the current app sounds. This path loads no models, so it
   is fast and needs no download.

If the critique is useful and the generated effects hold up in the app, it earns
a place. If not, the answer is no, and this doc is the receipt.

## What shipping it would look like

Not a dependency and not a bundled toolkit. The shape that fits:

- Detect an `earshot` install (config path, or a `command -v earshot` probe) and
  add its MCP tools only when present.
- When a task involves audio or video and earshot is missing, tell the user the
  install command once, instead of failing or silently skipping the QA step.
- Keep it out of the default tool list so tool-RAG never spends budget on it.

## Honest limits

- It cannot judge speech content or licensing. Transcription is still the speech
  toolkit's job.
- The author's own README says the realness model is easy to fool and that
  search-optimized sounds can pass every model check; the model-free
  measurements are the more trustworthy signal.
- All accuracy figures in the upstream README come from its own benchmarks on
  its own clips. Treat them as a starting hypothesis, not a spec.
- Licensing: the code is MIT. The two downloaded models are third-party (LAION
  CLAP, `MIT/ast-finetuned-audioset`); check their model cards before any
  redistribution, and check `skills/real-sound`'s vendored script attribution
  (upstream credits it to the Cinetic skill by the same author).

## See also

- [extra-skills.md](../extra-skills.md) - the video/media skills this would sit
  after.
- [features/connectors-and-mcp.md](../features/connectors-and-mcp.md) - how local
  MCP servers reach the agent.
- [features/skills.md](../features/skills.md) - how skills are discovered and
  enabled per agent.
- `brain/app/agent/toolkit/audio_analysis_toolkit.py` and
  `brain/app/agent/factory/multi_modal.py:165-186` - the current, speech-only
  audio surface.
