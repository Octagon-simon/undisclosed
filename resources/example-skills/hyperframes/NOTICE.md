# HyperFrames skills — provenance and attribution

These skills are vendored from the open-source **HyperFrames** project by HeyGen:

> https://github.com/heygen-com/hyperframes — `skills/` (branch `main`)

HyperFrames is licensed under the **Apache License 2.0** (see `LICENSE` in this
directory). The vendored copy is redistributed here unchanged apart from the
frontmatter parsing fixes in the host app (none of the skill content itself was
edited).

## What is bundled

This directory (`hyperframes/`, the mandatory router skill) and its sibling
example-skill directories are the 21 published HyperFrames skills:

`embedded-captions`, `faceless-explainer`, `figma`, `general-video`,
`hyperframes`, `hyperframes-animation`, `hyperframes-audio`, `hyperframes-cli`,
`hyperframes-core`, `hyperframes-creative`, `hyperframes-keyframes`,
`hyperframes-registry`, `hyperframes-studio`, `media-use`, `motion-graphics`,
`music-to-video`, `pr-to-video`, `product-launch-video`,
`remotion-to-hyperframes`, `slideshow`, `talking-head-recut`.

The six repo-internal skills under HyperFrames' `.claude/skills` and
`.agents/skills` are intentionally **not** bundled (upstream excludes them from
published installs too).

## Third-party material inside these skills

The skills bundle some third-party assets. Their licenses travel with them:

- **GSAP 3.15** (`music-to-video/references/motion-primitives/assets/gsap.min.js`,
  `talking-head-recut/assets/vendor/gsap.min.js`) — GreenSock, under the
  [GSAP Standard License](https://gsap.com/standard-license) (free for commercial
  and non-commercial use; **not** an OSI open-source license). See the header in
  each vendored file.
- **talking-head-recut** — its card design system is adapted from the MIT-licensed
  **vtake-skills** project; the required notice is retained at
  `talking-head-recut/NOTICE.md`.
- **Fonts** — Google Fonts / SIL OFL 1.1 (Inter, Caveat, Fredoka, EB Garamond,
  JetBrains Mono, Orbitron, and others), with OFL text kept beside the copies
  (e.g. `hyperframes-creative/frame-presets/code-editorial/fonts/OFL-*.txt`).
- **Sound effects** (`media-use/audio/assets/sfx/`) — Pixabay Content License;
  see `media-use/audio/assets/sfx/CREDITS.md`.

For the full upstream credit list (Remotion prior art, three.js, GSAP, Poly
Haven, and more), see the HyperFrames repository's `CREDITS.md`.
