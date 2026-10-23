# Extra skills (install on demand)

**What this is.** The app ships a small set of **bundled example skills** (frontend,
UI, design, and skill authoring). The video, media, and motion-design skills are
**not** bundled and are no longer kept in this repo. They live in their upstream
open-source projects, and you install one by pasting its URL into the agent.

This page lists every one of those skills, who publishes it, and how to install it.

---

## What ships vs what you install

| Where | Bundled? | Auto-installed? | Contents |
| --- | --- | --- | --- |
| `resources/example-skills/` | **Yes** (electron-builder `extraResources`) | **Yes** - synced into your skill store on startup | Frontend, UI, design, and skill-authoring skills |
| Upstream GitHub (this page) | **No** | **No** | Video, media, and motion skills |

The bundled set appears under **Examples** in the Skills screen. Everything on this
page you install yourself and it lands under **Your skills**.

## How to install (paste the URL)

1. Open the **skills folder** of a project from the tables below.
2. Click into the skill you want, then copy the URL from your browser's address bar.
   It looks like `https://github.com/<owner>/<repo>/tree/main/skills/<skill>`.
3. Paste that URL into the agent chat and ask it to install the skill, for example:

   > install this skill: https://github.com/heygen-com/hyperframes/tree/main/skills/hyperframes

4. The agent fetches the skill into your skills directory
   (`~/.undisclosed/skills/<name>/`). It shows up under **Your skills**; enable it
   per agent from there.

The `hyperframes` skill is the router the other HyperFrames skills route through, so
install it alongside whichever domain skill you want (for example `hyperframes` +
`product-launch-video`).

## Skills you can install

### HyperFrames, by [heygen-com](https://github.com/heygen-com)

Source: **https://github.com/heygen-com/hyperframes/tree/main/skills** (Apache-2.0)

| Skill | What it does |
| --- | --- |
| [`hyperframes`](https://github.com/heygen-com/hyperframes/tree/main/skills/hyperframes) | Mandatory entry point and router for any request to make, edit, animate, or render video, animation, or motion graphics. |
| [`hyperframes-core`](https://github.com/heygen-com/hyperframes/tree/main/skills/hyperframes-core) | The composition contract: structure, `data-*` timing attributes, tracks, sub-compositions, deterministic render, validation. |
| [`hyperframes-animation`](https://github.com/heygen-com/hyperframes/tree/main/skills/hyperframes-animation) | Atomic motion rules, scene blueprints, transitions, and the seven runtime adapters (GSAP, Lottie, Three.js, Anime.js, CSS, WAAPI, TypeGPU). |
| [`hyperframes-creative`](https://github.com/heygen-com/hyperframes/tree/main/skills/hyperframes-creative) | Non-animation creative direction: design spec, palettes, typography, narration, beat planning, brand/style decisions. |
| [`hyperframes-keyframes`](https://github.com/heygen-com/hyperframes/tree/main/skills/hyperframes-keyframes) | Punch-in/out, zoom, reframe, Ken Burns, camera moves, seek-safe 2D/3D keyframes, masks, SVG morph/draw. |
| [`hyperframes-audio`](https://github.com/heygen-com/hyperframes/tree/main/skills/hyperframes-audio) | Mixing placed audio: fades, crossfades, gain, ducking, music beds, effects, automation envelopes. |
| [`hyperframes-cli`](https://github.com/heygen-com/hyperframes/tree/main/skills/hyperframes-cli) | The HyperFrames CLI loop: init, add, capture, lint, preview, render, publish. |
| [`hyperframes-registry`](https://github.com/heygen-com/hyperframes/tree/main/skills/hyperframes-registry) | Search, install, and wire registry blocks/components before hand-building any named visual. |
| [`hyperframes-studio`](https://github.com/heygen-com/hyperframes/tree/main/skills/hyperframes-studio) | Working with a person on a HyperFrames project in Studio: plan, storyboard, build order, timeline layout. |
| [`general-video`](https://github.com/heygen-com/hyperframes/tree/main/skills/general-video) | Author or edit a custom composition when no specialized workflow fits (reels, montages, freeform builds). |
| [`motion-graphics`](https://github.com/heygen-com/hyperframes/tree/main/skills/motion-graphics) | Short, design-led motion graphics: kinetic type, stat count-up, logo stings, lower-thirds, overlays. |
| [`slideshow`](https://github.com/heygen-com/hyperframes/tree/main/skills/slideshow) | Author a navigable HyperFrames slideshow / pitch deck (not a rendered MP4). |
| [`product-launch-video`](https://github.com/heygen-com/hyperframes/tree/main/skills/product-launch-video) | Turn a product/marketing URL or brief into a launch or promo video. |
| [`pr-to-video`](https://github.com/heygen-com/hyperframes/tree/main/skills/pr-to-video) | Turn a GitHub pull request into a code-change explainer video. |
| [`faceless-explainer`](https://github.com/heygen-com/hyperframes/tree/main/skills/faceless-explainer) | Turn text, notes, or a topic into a faceless explainer video. |
| [`talking-head-recut`](https://github.com/heygen-com/hyperframes/tree/main/skills/talking-head-recut) | Package an existing talking-head/interview/podcast video with graphic overlay cards. |
| [`embedded-captions`](https://github.com/heygen-com/hyperframes/tree/main/skills/embedded-captions) | Add captions/subtitles to a talking-head video without editing the footage. |
| [`music-to-video`](https://github.com/heygen-com/hyperframes/tree/main/skills/music-to-video) | Turn a music track into a beat-synced video (lyric, slideshow, kinetic promo). |
| [`media-use`](https://github.com/heygen-com/hyperframes/tree/main/skills/media-use) | Agent Media OS: resolve BGM, SFX, images, icons, brand logos, voice, grades, LUTs. |
| [`remotion-to-hyperframes`](https://github.com/heygen-com/hyperframes/tree/main/skills/remotion-to-hyperframes) | Port an existing Remotion (React) composition to HyperFrames HTML. |
| [`figma`](https://github.com/heygen-com/hyperframes/tree/main/skills/figma) | Import Figma assets, tokens, components, and storyboards into a HyperFrames composition. |

### Launch videos, by [latent-spaces](https://github.com/latent-spaces)

Source: **https://github.com/latent-spaces/brag/tree/main/skills** (MIT)

| Skill | What it does |
| --- | --- |
| [`brag`](https://github.com/latent-spaces/brag/tree/main/skills/brag) | Turn the current project website into a short, shareable launch video (via HyperFrames). |
| [`brag-slim`](https://github.com/latent-spaces/brag/tree/main/skills/brag-slim) | Same launch-video goal, one file, no bundled assets, built entirely with tools on the machine. |

## Audio and video QA (candidate, not packaged)

**[earshot](https://github.com/Leonxlnx/earshot)** (MIT) gives an agent ears for
non-speech audio: `describe`, `match`, `find`, `timeline`, `critique`,
`realness`, and a no-model effects bank (`sfx`). It is the measurement half of
the media pipeline above: those skills make and mix the sound, earshot checks
whether it landed.

Not bundled, and not a one-URL install: the skills are only instructions, so the
Python package and `ffmpeg`/`ffprobe` must be installed first. It pulls
`torch` and ~1.1 GB of models, which is why it is not a dependency.

- Skills: `https://github.com/Leonxlnx/earshot/tree/main/skills/earshot` and
  `.../skills/real-sound`
- Full evaluation, install steps, and why we did not adopt it:
  [plans/earshot-optional-audio-tooling.md](plans/earshot-optional-audio-tooling.md)

## Attribution

- **HyperFrames** (`hyperframes*`, `general-video`, `motion-graphics`, `slideshow`,
  `product-launch-video`, `pr-to-video`, `faceless-explainer`, `talking-head-recut`,
  `embedded-captions`, `music-to-video`, `media-use`, `remotion-to-hyperframes`,
  `figma`) is published by HeyGen under **Apache-2.0**
  (https://github.com/heygen-com/hyperframes). `talking-head-recut`'s card design
  system is adapted from the MIT-licensed
  [notedit/vtake-skills](https://github.com/notedit/vtake-skills).
- **`brag` / `brag-slim`** are published by latent-spaces under **MIT**
  (https://github.com/latent-spaces/brag).

## See also

- [features/skills.md](features/skills.md) - the skill system itself.
- [features/curated-skill-catalog.md](features/curated-skill-catalog.md) - the
  planned browse-and-install catalog.
