# Iris, Page Screenshots, and Image Reader smoke test

Pinned to commit `5b181ae` plus the working-tree changes from this session.
Nothing here changes code. It only exercises the new surface end to end.

## The prompt to paste

Paste this as a fresh task in a new chat. It is deliberately specific, so the
agent cannot fake the result with prose.

```text
I am smoke-testing three new features: the page camera (iris), the image
reader, and vision-model routing. Follow these steps exactly and report raw
evidence. Do NOT use browser_* tools for this task, and do not use
take_screenshot_and_read_image.

1. Load both capabilities in ONE call: load_capability(["Page Screenshots", "Image Reader"]).
2. Create .scratch/vision-oracle/index.html in the workspace. It must contain:
   an h1 with the exact text ORACLE-7F3A, one short paragraph, and CSS with a
   @media (prefers-color-scheme: dark) block that sets body background
   #101418 and text #f2f5f7; the light case must be background #ffffff and
   text #1a1a1a. Then serve that folder with python3 -m http.server 8811 in
   the background.
3. capture_page(url="http://127.0.0.1:8811", sizes=["desktop","iphone"], full_page=True).
   Report the exact path and pixel dimensions of each PNG it returns.
4. capture_page(url="http://127.0.0.1:8811", selector="h1", padding=32, dark=True).
   Report the path and the cropped image dimensions, and the exact text of the
   line in the result that says whether images were attached.
5. Call read_image on the dark h1 crop you just made, with the instruction:
   "Report the exact heading text, the background color (give the hex if you
   can), and whether the text is light or dark." Answer only from what the tool
   returns. If you could not actually see the image, say so instead of guessing.
6. Stop the http server, then list every PNG you created with its byte size.
7. Final answer: a plain-text table with columns step, tool called, result
   (path, dimensions, or error). No markdown table.
```

## What each step actually proves

1. `Page Screenshots` and `Image Reader` are deferred capabilities, so they must
   appear in `<loadable_capabilities>` and must be loadable in one call. In the
   UI you should now see a **Capabilities** group in the execution summary with
   a camera icon for Page Screenshots and an eye/monitor icon for Image Reader.
   Before `5b181ae` this row was collected as `other` and never rendered.
2. Gives the test a controlled oracle: a known token and a known dark palette,
   so a wrong answer is a real failure instead of a taste judgment.
3. Proves the multi-viewport path: one tool call, two iris subprocesses, desktop
   and iphone presets, full-page capture.
4. Proves element crop (`selector` + `padding`) and `prefers-color-scheme` dark
   emulation, which are separate code paths from step 3.
5. Proves `read_image` routes through `vision_backend_for()`, not the chat
   model. This is the part that was broken before `dfc1084`.
6. Proves files landed on disk and the server was cleaned up.

## What you should see with your current config

Your preferred chat row is `deepseek-v4-flash` (no `vision` in the id), and the
vision row is `deepseek-v4-flash-vision-exp` (id 10, deepseek). So:

- Because the chat model is text-only, `capture_page` in steps 3 and 4 returns
  the path list ending in `No images attached: deepseek-v4-flash is not known
  to accept image input. Open a path with read_image to view it.` That line
  names the vision gate, so a missing attachment is never ambiguous.
- Step 5 is where pixels actually reach a model, via the vision row. The answer
  must contain `ORACLE-7F3A`, a dark background (~`#101418`), and light text.
- If you switch the chat model to `claude-sonnet-5` or any vision id, step 3 and
  4 should instead end in `Images attached to context: 1.` (or `2.` for the
  two-viewport call) and the PNG should show up inline in the tool result.
- Color scheme is deterministic: a capture without `dark=True` is pinned to
  light, and `dark=True` is pinned to dark. Before that change, `dark=False`
  left the scheme to Chrome, which inherits the host appearance, so on a
  dark-mode Mac the light branch rendered dark and `dark=False` and `dark=True`
  produced identical pixels.

Screenshots default to `~/.undisclosed/screenshots/<task_id>/`.

## Optional leak-proof check

The oracle page is written by the agent, so the chat model technically knows the
token. If you want a read that cannot be guessed, attach an image to the chat
and ask:

```text
Use read_image on the attached image and tell me one detail that is only
visible in the picture, then state the image dimensions. Do not use any other
tool to inspect it.
```

Anything the agent could not have typed is a clean pass.

## Failure signatures

- `Error: the page camera binary (iris) is not installed` -> the binary is
  missing at `resources/binaries/iris/<os>-<arch>/iris`. Run
  `npm run fetch:iris` and restart the brain.
- `load_capability` returns "unknown capability" -> `_lazy_single_agent_extras()`
  is off (tool RAG disabled), so the toolkits were built eagerly. The tools
  should then exist without the load step; that is expected, not a bug.
- Step 5 returns `Error: no vision-capable model is configured` -> the
  providers file has no row matching a vision marker and
  `UNDISCLOSED_VISION_MODEL` is unset. Id 10 should satisfy this.
- Step 5 returns a description that matches a white page -> either the dark
  crop was not dark (iris ignored the flag) or `read_image` opened the wrong
  file. Compare the PNG on disk before blaming the vision model.
- Any step opens the app CDP browser on port 9222 -> that is the bug the next
  doc covers, not this feature. iris launches its own short-lived browser and
  never touches 9222.

## Terminal checks while it runs

```bash
# screenshots produced by this task
ls -lt ~/.undisclosed/screenshots/*/ | head -20

# iris processes (expected: short-lived, one per shot, then gone)
pgrep -fl 'iris ' | head

# app CDP browser (expected: unchanged during this test)
pgrep -fl 'remote-debugging-port=9222'
```

If the second list shows nothing after the task and the third list is unchanged,
the page camera is isolated the way it should be.
