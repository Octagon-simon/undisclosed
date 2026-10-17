# Installing Undisclosed

This guide is for anyone installing Undisclosed for the first time, on macOS,
Windows, or Linux. No prior setup, no terminal required for the basics.

There are two ways to get the app, and they lead to the same files:

1. **The download button on the homepage.** Click **Download** and it takes you
   straight to the GitHub Releases page for the repo.
2. **GitHub Releases directly.** Go to
   [github.com/Octagon-simon/undisclosed/releases](https://github.com/Octagon-simon/undisclosed/releases)
   and pick the newest release at the top of the list.

One honest heads-up before you start: the builds are **not code-signed or
notarized yet**. macOS and Windows will each warn you the first time you open the
app. That is expected for an unsigned build, and the steps below show how to get
past it. Notarization is coming soon; once it ships, those warnings disappear and
these extra steps go away with them.

---

## What to download

Pick the file that matches your computer. On the Releases page, open the newest
release and look under **Assets**.

| Your computer | File to download |
| --- | --- |
| macOS, Apple Silicon (M1/M2/M3/M4 and later) | the `.dmg` with `arm64` in the name |
| macOS, Intel | the `.dmg` with `x64` (or `x86_64`) in the name |
| Windows | the `.exe` (a setup installer) |
| Linux, most distros (portable) | the `.AppImage` |
| Linux (Debian/Ubuntu, installs system-wide) | the `.deb` |

If you are not sure which macOS chip you have: Apple menu → **About This Mac**.
"M1"/"M2"/"M3"/"M4" (or "Apple M…") means Apple Silicon; "Intel" means the other
one.

Every release ships all three platforms at once, so you only need one file.

---

## macOS

1. Download the `.dmg` (see the table above).
2. Open the `.dmg`, then drag **Undisclosed** into your **Applications** folder.
3. Eject the disk image (drag it to the Trash, or press the eject icon).
4. The **first launch will be blocked by Gatekeeper** with a message like
   *"Undisclosed can't be opened because Apple cannot check it for malicious
   software."* This is the notarization warning, not a problem with the file.

   To open it anyway, do **one** of these:

   - **Right-click method (easy):** in **Applications**, right-click (or
     Control-click) **Undisclosed** → **Open** → click **Open** again in the
     dialog. You only need to do this once.
   - **Settings method:** try to open the app, then go to **System Settings →
     Privacy & Security** and click **Open Anyway** next to the Undisclosed
     message. Confirm with your password.
   - **Terminal method (if the above are blocked):** run
     ```bash
     xattr -cr /Applications/Undisclosed.app
     ```
     then open the app normally.

5. After one successful open, launch it like any other app (Launchpad, Spotlight,
   or Applications).

---

## Windows

1. Download the `.exe` setup file.
2. Double-click it. **Windows SmartScreen** will likely show
   *"Windows protected your PC"* because the build isn't signed yet.

   Click **More info**, then **Run anyway**.

3. Follow the installer (choose a location if you want; the default is fine) and
   finish. A shortcut appears on your Desktop and Start menu.
4. If Windows silently blocks the file before it runs (nothing happens on
   double-click), right-click the downloaded `.exe` → **Properties** → tick
   **Unblock** at the bottom of the General tab → **Apply**, then run it again.
5. Launch **Undisclosed** from the Start menu or the Desktop shortcut.

---

## Linux

Use the file that matches how you like to install things.

### AppImage (portable, no install)

1. Download the `.AppImage`.
2. Make it executable and run it:
   ```bash
   chmod +x Undisclosed-*.AppImage
   ./Undisclosed-*.AppImage
   ```
3. If it fails with a message about FUSE (common on Ubuntu 22.04 and newer),
   install the compatibility library once, then run it again:
   ```bash
   sudo apt install libfuse2
   ```

### .deb (Debian / Ubuntu)

1. Download the `.deb`.
2. Install it:
   ```bash
   sudo dpkg -i Undisclosed-*.deb
   ```
3. If `dpkg` reports missing dependencies, let apt fix them:
   ```bash
   sudo apt -f install
   ```
4. Launch **Undisclosed** from your applications menu, or run `undisclosed` in a
   terminal.

---

## First launch

Undisclosed is two parts that start together:

- the **editor** (the window you see), and
- the **brain**, a local agent backend on your machine.

On first launch the app starts the brain for you, so you normally do not have to
do anything. You can then bring your own model keys or point it at a local model.
Nothing needs to be configured before the app opens.

If the status ever reads like the backend is offline, give it a few seconds on the
very first start (the brain is warming up), then retry. The in-app help and the
`.env.sample` file in the repo document the optional knobs.

---

## Troubleshooting

- **"Apple cannot check it for malicious software."** Expected on an unsigned
  build. Use the right-click → Open step above (or `xattr -cr`).
- **"Windows protected your PC."** Expected on an unsigned build. Click **More
  info** → **Run anyway**, or unblock the file from its Properties.
- **The app opens but the agent never responds.** Give the brain a few seconds on
  the first run. If it persists, restart the app so the brain relaunches.
- **I don't see a build for my platform.** Every release ships macOS, Windows, and
  Linux together. If the newest entry is marked **Pre-release**, that is expected
  while the app is in beta; it has the same download assets.

Once notarization and code signing are in place, the macOS and Windows warnings
above will no longer appear.
