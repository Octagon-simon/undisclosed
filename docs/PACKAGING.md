<!-- Copyright (c) 2026 Simon Ugorji -->

# Packaging Undisclosed as an installable desktop app

This document is the plan for turning the current dev setup into downloadable
installers (`.dmg` / `.exe` / `.AppImage`) built and published by GitHub
Actions on every release tag.

> Status: **not built yet.** Today the app runs as a Theia **browser** target
> (`theia: { target: "browser" }` in the root `package.json`) on `:3000`, with
> the FastAPI **brain** started separately on `:5001` via `scripts/brain.sh`.
> This doc is the migration path, not a description of something that exists.

---

## 0. Build & install locally (macOS self-install)

CI builds macOS for both Apple Silicon (`macos-15`) and Intel (`macos-15-intel`), but
the installers are **unsigned** (Gatekeeper warns on first open). You can also build
an installable `.dmg` on your own Mac. Two toolchain requirements — Theia's
native modules are picky:

- **Node 18–20** (not 22/24). `nvm use 20` (an `.nvmrc` pins 20).
- **Python ≤3.11 for node-gyp** — Python 3.12+ removed `distutils` and node-gyp
  9.x needs it. Easiest: reuse the brain's 3.11 venv:
  `export npm_config_python="$PWD/brain/.venv/bin/python"` (or `pip install
  setuptools` for your python3).

Then, from the repo root:

```bash
nvm use 20
export npm_config_python="$PWD/brain/.venv/bin/python"
npm run desktop:install                       # install apps/desktop deps
npm --prefix apps/desktop run rebuild         # rebuild native modules for Electron
npm run dist:mac                              # freeze brain + build + package .dmg
```

The `.dmg` lands in `apps/desktop/dist/`. It's **unsigned** (`identity: null`), so
on first open: right-click → Open, or `xattr -cr /Applications/Undisclosed.app`.

`npm run dist:mac` runs `dist:brain` (PyInstaller freeze) → `build:agent-ui` →
the Electron build + electron-builder, so the `.dmg` is self-contained (the brain
binary is bundled under `resources/brain/` and auto-launched by `BrainLauncher`).

---

## 1. What has to ship together

Undisclosed is **two processes**:

| Process | What it is | Dev command | Port |
| --- | --- | --- | --- |
| **Frontend** | Theia (Eclipse Theia + our `undisclosed-*` extensions + the agent embed) | `npm start` | 3000 |
| **Brain** | Vendored FastAPI/uvicorn app + its own `brain/.venv` | `scripts/brain.sh start` | 5001 |

An installable app must bundle **both** and manage their lifecycle so the user
double-clicks one icon and everything comes up. The standard way to do this
with Theia is an **Electron** shell that (a) hosts the Theia frontend and
(b) spawns the brain as a child ("sidecar") process.

```
Undisclosed.app
├─ Electron main process
│   ├─ starts Theia backend (Node)         ← the editor
│   └─ spawns the brain sidecar (:5001)     ← the agent
└─ renders the Theia frontend in a window
```

---

## 2. Migration steps

### Step 1 — Add an Electron target for Theia

Theia supports an `electron` target alongside `browser`. Create an Electron
application package (e.g. `apps/desktop/`) that lists the same
`theiaExtensions` the browser app uses, plus `@theia/electron`.

- Root or app `package.json`: `"theia": { "target": "electron", ... }`.
- Keep `applicationName: "Undisclosed"` (already set).
- Build with `theia build` then package with **electron-builder** (Theia's
  recommended packager). electron-builder produces the platform installers.

Key scripts to add to the Electron app package:

```jsonc
{
  "scripts": {
    "build": "theia build --mode production",
    "package": "electron-builder -c electron-builder.yml",
    "package:preview": "electron-builder --dir -c electron-builder.yml"
  }
}
```

### Step 2 — Bundle the brain (Python) so users don't install Python

The brain is Python. Users can't be expected to provision `brain/.venv`. Pick
**one** strategy:

- **PyInstaller (recommended).** Freeze the brain into a single self-contained
  executable (`undisclosed-brain`) per OS. No Python required on the user's
  machine. Build it in CI (see the workflow below):
  ```bash
  cd brain
  pip install pyinstaller
  pyinstaller --onefile --name undisclosed-brain \
    --collect-all camel --collect-all app \
    main.py
  ```
  Watch for hidden imports (CAMEL, toolkits, playwright). Add
  `--collect-all`/`--hidden-import` as the build surfaces missing modules.
- **Bundled Python + venv** (fallback). Ship a relocatable Python and run
  `setup-brain.sh` on first launch. Simpler to get working, larger install,
  slower first start.

The frozen binary is handed to electron-builder via `extraResources` so it
lands inside the app bundle:

```yaml
# electron-builder.yml
extraResources:
  - from: "brain/dist/undisclosed-brain"      # PyInstaller output (per-OS)
    to: "brain/undisclosed-brain"
```

### Step 3 — Spawn + supervise the brain from Electron main

In the Electron main process, start the brain sidecar before opening the window
and kill it on quit. Sketch:

```ts
import { spawn } from "node:child_process";
import { join } from "node:path";

let brain;
function startBrain() {
  const bin = join(process.resourcesPath, "brain", "undisclosed-brain");
  brain = spawn(bin, [], {
    env: { ...process.env, UNDISCLOSED_BRAIN_PORT: "5001" },
    stdio: "inherit",
  });
  brain.on("exit", (code) => console.error("[brain] exited", code));
}
app.on("ready", startBrain);
app.on("will-quit", () => brain?.kill());
```

- Health-gate the window on `GET http://127.0.0.1:5001/health` returning 200
  (the frontend already probes this).
- Consider a random free port instead of a hard-coded 5001 to avoid clashes,
  and pass it to the frontend via `VITE_BRAIN_ENDPOINT` / a runtime config.
- Ship the `.env` handling as-is: the brain still auto-loads `.env` files (see
  `.env.sample`), so power users can drop keys next to the app.

### Step 4 — electron-builder config

```yaml
# electron-builder.yml
appId: dev.octagon.undisclosed
productName: Undisclosed
directories:
  output: dist-installers
mac:
  target: [dmg, zip]
  category: public.app-category.developer-tools
  hardenedRuntime: true          # required for notarization
win:
  target: [nsis]
linux:
  target: [AppImage, deb]
extraResources:
  - from: "brain/dist/undisclosed-brain"
    to: "brain/undisclosed-brain"
```

---

## 3. GitHub Actions: build + publish on a release tag

Trigger on `v*` tags. A 3-OS matrix builds the brain binary, builds the Theia
Electron app, runs electron-builder, and uploads installers to a GitHub
Release. Drop this at `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: write            # needed to create the GitHub Release

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: macos-latest
          - os: windows-latest
          - os: ubuntu-latest
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      # 1) Freeze the brain into a self-contained binary
      - name: Build brain binary
        working-directory: brain
        run: |
          python -m pip install -r requirements.txt pyinstaller
          pyinstaller --onefile --name undisclosed-brain \
            --collect-all camel --collect-all app main.py

      # 2) Build the Theia Electron app
      - name: Install & build frontend
        run: |
          npm ci
          npm run build:agent-ui        # builds + syncs the agent embed
          npm run build                 # theia build (electron target)

      # 3) Package installers
      - name: Package
        run: npm run package --workspace apps/desktop
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          # macOS signing/notarization (optional but recommended):
          # CSC_LINK: ${{ secrets.MAC_CERT_P12_BASE64 }}
          # CSC_KEY_PASSWORD: ${{ secrets.MAC_CERT_PASSWORD }}
          # APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID: ...

      - name: Upload installers to the Release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            dist-installers/**/*.dmg
            dist-installers/**/*.exe
            dist-installers/**/*.AppImage
            dist-installers/**/*.deb
```

Cut a release by tagging: `git tag v0.1.0 && git push origin v0.1.0`.

### Pre-release (beta) builds

To ship a beta off a branch (e.g. `upgrade/theia-1.76`) **without touching the
stable release**, cut a pre-release tag instead. The workflow publishes any tag
with a semver pre-release suffix (`v*-beta.*`, `-rc.*`, …) as a GitHub
**pre-release**, which keeps `main`'s release as "latest":

```bash
npm run release:beta          # first run: 0.0.9 -> 0.1.0-beta.0
npm run release:beta          # next run:  0.1.0-beta.0 -> 0.1.0-beta.1
# or, explicitly:
npm run release -- minor beta  # 0.0.9 -> 0.1.0-beta.0
npm run release -- prerelease beta
```

The bump is committed on the **current branch** only, so `main` is untouched.

---

## 4. Code signing: whose identity ships

**Default state: nothing is signed.** `electron-builder.yml` sets
`mac.identity: null` and `.github/workflows/release.yml` sets
`CSC_IDENTITY_AUTO_DISCOVERY: "false"`, so `npm run dist:mac` (local or CI)
produces an unsigned app no matter which certificates sit in the keychain.
Unsigned is noisy for users (Gatekeeper warns on first open) but it is safe:
it cannot accidentally carry a real identity.

**The release identity must be Simon's own Apple Developer team.** A Developer
ID issued to any other team (an employer's, a client's, or a borrowed cert) is
not to sign distributed builds, DMGs included, even when `codesign --verify`
passes on it. Local dev installs are the only exception.

**When your own Developer ID exists**, three things have to change together:

1. Point the build at your identity. Either drop `identity: null` and let
   electron-builder auto-discover (disambiguate with `CSC_NAME`), or set the
   full common name explicitly:

   ```yaml
   mac:
     identity: "Developer ID Application: <Your Name> (<YOURTEAMID>)"
     hardenedRuntime: true      # notarization requires it
     entitlements: "build/entitlements.mac.plist"
     entitlementsInherit: "build/entitlements.mac.plist"
   ```

2. Ship entitlements. Electron plus Theia's native modules (`node-pty`,
   ripgrep) need at minimum `com.apple.security.cs.allow-jit`,
   `com.apple.security.cs.allow-unsigned-executable-memory` and
   `com.apple.security.cs.disable-library-validation`. Without the last one the
   plugin host fails to load its `.node` binaries under hardened runtime.

3. Notarize after signing, inside the same job:

   ```sh
   ditto -c -k --keepParent "apps/desktop/dist/mac-arm64/Undisclosed.app" app.zip
   xcrun notarytool submit app.zip --apple-id "$APPLE_ID" \
     --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" --wait
   xcrun stapler staple "apps/desktop/dist/mac-arm64/Undisclosed.app"
   ```

   Notarization requires a **secure timestamp** (`--timestamp` on
   `codesign`). On the network used during the 2026-10-28 attempt, Apple's
   timestamp server was unreachable, so that build could not be notarized even
   though it signed. Check `xcrun notarytool` reachability before promising a
   notarized release.

Verify before publishing, not after:

```sh
codesign -dv --verbose=4 /Applications/Undisclosed.app   # Identifier + TeamIdentifier
codesign --verify --deep --strict --verbose=2 /Applications/Undisclosed.app
spctl -a -vvv /Applications/Undisclosed.app              # accepted / notarized
```

Keep the `.p12`, the app-specific password and the team id in CI secrets. Never
in the repo, and never as a literal in `electron-builder.yml`.

### TCC permissions are user-granted, not signed

Entitlements cannot grant Screen Recording or Accessibility; the user grants
them per binary in System Settings. Two features depend on those grants:

- **App Screenshots** (macOS window capture) needs Screen Recording.
- **Desktop Control** (mouse, keyboard, scroll, and the accessibility tree) needs
  Accessibility. The same grant covers both halves, so without it macOS drops
  synthetic events silently and `AXUIElement` returns nothing; the toolkit
  reports the missing grant either way instead of pretending to act.

The grant attaches to the process that posts the events. In a packaged build
that is `Undisclosed.app`; in development the brain is a child of your
terminal, so grant the terminal (or the IDE) and restart it. A rebuild that
changes the signature can look like a brand new binary to TCC; force a fresh
prompt with `tccutil reset Accessibility dev.octagon.undisclosed` (and the
Screen Recording equivalent). Resetting clears the old tick from the list;
enable the app again and restart it, because TCC caches the decision for the
life of the process.

TCC, the notification database and macOS Launch Services all key off the
bundle id, so changing `appId` in `electron-builder.yml` gives you a different
app as far as macOS is concerned: the grants do not carry over, and you have to
enable the new build again. Before `dev.octagon.undisclosed` the id was
`ai.undisclosed.app`; installs built with that id leave stale Accessibility and
Screen Recording rows behind, which `tccutil reset Accessibility
ai.undisclosed.app` clears.

Desktop Control is also gated by channel. Only turns that arrive on the
`desktop` channel get it; a Slack, WhatsApp, Lark or web turn runs on the same
brain with no mouse, because whoever wrote that message is not sitting at this
Mac. Widen it per deployment with
`toolkit_config={"desktop": {"channels": ["desktop", "cli"]}}`.

---

## 5. Caveats / decisions still open

- **Code signing.** Unsigned macOS/Windows builds trigger Gatekeeper/SmartScreen
  warnings, and macOS notifications stay denied until the bundle is signed
  under its real bundle id. See "Code signing: whose identity ships" above for
  what has to be in place. Windows needs an Authenticode cert.
- **Playwright/Chromium for the browser toolkit.** The brain launches a CDP
  Chromium. Decide whether to bundle a browser or rely on the user's Chrome
  (`UNDISCLOSED_CHROME_PATH` / `UNDISCLOSED_CDP_URL`). This affects install size.
- **Size.** PyInstaller + CAMEL + (optional) Chromium is large (hundreds of MB).
  Acceptable for a dev tool; note it in release notes.
- **Auto-update.** electron-builder supports `electron-updater` against GitHub
  Releases if you want in-app updates later.
- **First-run keys.** Models are configured in-app (BYOK); no keys need to ship.

---

## 6. TL;DR order of work

1. Stand up an Electron Theia app package (`apps/desktop/`).
2. Freeze the brain with PyInstaller; spawn it from Electron main.
3. Add `electron-builder.yml` with the brain as `extraResources`.
4. Add `.github/workflows/release.yml` (the matrix above).
5. Tag `vX.Y.Z` → installers attach to the GitHub Release.
