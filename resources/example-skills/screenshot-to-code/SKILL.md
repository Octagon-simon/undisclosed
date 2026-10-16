---
name: screenshot-to-code
description: Convert a UI screenshot or design mockup into clean, production-ready HTML/CSS (and optional React/Tailwind). Works from any screenshot/image of an interface — web pages, dashboard mockups, mobile app screens, desktop app UIs, Figma/design exports, or design DPs. Use whenever the user shares a screenshot and asks to reproduce it as code, build a matching frontend, generate HTML for a design image, or turn a mockup into a page. Trigger phrases: "convert this screenshot to code", "build this as HTML", "recreate this design", "turn this mockup into a page", "make code for this image". The workflow detects UI blocks, understands the layout structure, and synthesizes faithful, editable front-end code.
license: Proprietary. LICENSE.txt has complete terms
---

# Screenshot-to-Code

Recreate any UI screenshot or design mockup as clean, editable HTML/CSS. The approach mirrors the ScreenCoder methodology: **detect components → understand layout → synthesize per-block code → assemble** — but runs entirely through the agent's available tools, so it needs no ML model, no API key, and no external service.

## When to use
Use this whenever the user gives you a screenshot/image of an interface and wants its code. Works for landing pages, dashboards, signup forms, navs, cards, modals, mobile screens, and full desktop UIs.

## Core principle (ScreenCoder-style, tool-light)
Don't try to write one giant blob of HTML after a glance. Break the image into logical **blocks** (navbar, hero, cards, footer, form, table, sidebar, etc.), understand the layout relationship between them, then generate code for each block and assemble the page. This guarantees structural fidelity and makes the output editable.

## Workflow

### 1. Read the image & extract structure
If the image is local, locate the file first. Analyze it to recover **text content** and **estimated regions** for each UI element. On macOS, extract text with the bundled Vision OCR helper (`scripts/ocr_swift.sh <image>`), which returns lines with bounding boxes. Also run optional block detection (`scripts/detect_blocks.py <image>`) to find large layout regions.

If the image is provided as a URL, fetch it locally first (`curl -L -o /tmp/design.png "<url>"`) before analysis.

### 2. Map the structure into blocks
From the OCR text + detected regions, identify the page sections and their relationship:
- **Header/Nav**: top bar with logo, nav links, search, CTA.
- **Hero**: headline, subhead, buttons, illustration/image.
- **Content rows**: feature cards, lists, grids, tables.
- **Controls**: forms, inputs, buttons, checkboxes, tabs, dropdowns.
- **Aside/Sidebar**: secondary nav, filters, panels.
- **Footer**: links, copyright, columns.

Determine layout: which blocks are stacked vertically vs. side-by-side, equal-width columns vs. fixed sidebar, wrapping grids. Note the color palette, typography (headline vs. body), spacing, and border/radius style from the screenshot.

### 3. Generate code block by block
Write semantic, responsive HTML5 with a clean linked `<style>` block (or Tailwind classes if the repo uses Tailwind, or JSX components if converting to React). Follow these conventions:

- Use **semantic elements**: `<header>`, `<nav>`, `<main>`, `<section>`, `<article>`, `<aside>`, `<footer>`, `<form>`, `<table>`.
- **System font stack** by default (`system-ui, -apple-system, Segoe UI, Roboto, sans-serif`) — no external fonts unless the design clearly calls for a specific one and it's available.
- **CSS custom properties** for colors/spacing so the user can re-theme easily:
  ```css
  :root { --bg:#fff; --surface:#f5f5f7; --ink:#1d1d1f; --muted:#6e6e73; --accent:#0a84ff; --radius:12px; }
  ```
- Use **flexbox/grid** for layout matching the detected structure. Use `grid-template-columns: repeat(auto-fit, minmax(240px,1fr))` for fluid card grids.
- Reproduce the screenshot's **alignment** (centered vs. left), **spacing rhythm**, and **visual weight**. For icons, use inline SVG or emoji/text glyphs rather than external icon-CDNs. Placeholder images → clearly-labeled `<img>` with `alt` describing the source image.
- Make it **responsive**: collapse multi-column layouts to single column below ~640px.

### 4. Reproduce fidelity details
- Match the **color of surfaces** (page bg vs. cards vs. accents) from the screenshot.
- Match **typographic hierarchy**: size/weight of the biggest headline vs. supporting text.
- Match **button styles**: filled primary, ghost/secondary, their radius and hover states (add `:hover` for interactive cues).
- Match **spacing**: padding of containers, gap between sections.
- If forms/inputs appear, build real `<input>`/`<label>` hierarchy with proper `type`.

### 5. Deliver
Write the result to a `.html` file (or the appropriate file type for an existing project) in the working repo. If the user wants an isolated demo, write `design.html` and offer a preview. Summarize what was recreated, note any inferred details (e.g., "this looks like a placeholder image"), and invite refinements ("want the variant button to be ghost style?").

## Accuracy standards
- **Fidelity first**: the produced code must look like the screenshot — right layout, right dominant colors, right hierarchy. If the image is low-res or ambiguous, state assumptions explicitly.
- Prefer a **few real components** over padding the screen with fake blocks you didn't actually see.
- When the screenshot clearly contains real text, reproduce that text (don't invent lorem ipsum for visible copy).

## Bundled scripts
- `scripts/ocr_swift.sh <image>` — macOS Vision OCR; prints lines with normalized bounding boxes `x,y,w,h` for positioning.
- `scripts/detect_blocks.py <image>` — optional OpenCV-based coarseness to find large homogeneous rectangles (call only if image analysis feels fuzzy).

## Notes
- macOS is expected (Vision OCR). On non-macOS, fall back to reading the image directly.
- This skill produces code; it does not require external services or API keys.
