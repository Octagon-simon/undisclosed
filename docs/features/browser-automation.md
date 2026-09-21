# Browser automation, live view, and take-control

**Problem.** An agent that can "use the browser" is only useful if it actually
has a browser, and only trustworthy if the human can see and intervene.

Two concrete gaps drove this work:

1. The desktop app used to provide the CDP browser via Electron. The standalone
   brain had none, so browser tools failed and the agent silently fell back to
   MCP or gave up.
2. The agent's browser ran offscreen; the user had no idea what it was doing, and
   could not take over at a login or a CAPTCHA.

**Solution.** Launch our own CDP Chromium, expose a live screencast, and let the
user take control from the panel.

---

## Launching a CDP Chromium

`brain/app/utils/browser_launcher.py` provides `ensure_cdp_browser_endpoint`.
When neither hands nor `UNDISCLOSED_CDP_URL` provide a browser, the brain launches
its own. `_find_chrome_executable` discovers an installed Chrome/Chromium,
including the Playwright browser cache (`ms-playwright`), with an
`UNDISCLOSED_CHROME_PATH` override. It uses a **persistent profile** so logins
survive restarts. (`b078ccf`.)

Capability detection (`brain/app/hands/capabilities.py`) only advertises the
browser hand when a CDP endpoint is configured/reachable, the runtime is Electron,
or a local browser can be provisioned.

## Live view + take-control

`brain/app/controller/browser_stream_controller.py` exposes a `/browser/stream`
**WebSocket** that speaks raw CDP over websockets + httpx (no python-playwright
dependency):

- discover the page target and attach a second DevTools client,
- force a render surface with `Emulation.setDeviceMetricsOverride` (the agent's
  window is offscreen, so it composites nothing otherwise),
- `Page.startScreencast` and relay frames (DPR-aware, quality 85),
- forward mouse/keyboard as `Input.dispatch*`.

The frontend `BrowserTakeControl` component renders frames to a canvas; "Take
control" forwards input and pauses the agent via the existing `/take-control`
endpoint. Follow-up work (`228c7bc`) added a **tab-follow watcher** that rebinds
the screencast when the agent opens a new page or closes the shown tab, and made
viewport state survive rebinds.

## Downloads

`hybrid_browser_toolkit` defaults the download directory to
`~/.undisclosed/downloads`, so a `download_file` action works instead of failing
with no download dir.

## Why raw CDP

Using raw CDP over a WebSocket keeps the brain free of a heavyweight,
version-sensitive `playwright` dependency, and lets us attach a *second* DevTools
client to the same page the agent is driving, which is what makes live view and
take-control possible at all.

## Where it lives

- Launch: `brain/app/utils/browser_launcher.py`
- Stream/take-control backend: `brain/app/controller/browser_stream_controller.py` (+ `router.py`)
- Live view UI: `agent-ui/src/components/BrowserAgentWorkspace/BrowserTakeControl.tsx`
- Capability gating: `brain/app/hands/capabilities.py`

## Key commits

`b078ccf` (launch a CDP Chromium), `cf60a06` (live view + take-control),
`228c7bc` (follow agent tabs, downloads dir, brain stop/restart fixes).
