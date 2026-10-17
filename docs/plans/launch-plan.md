# Undisclosed launch plan

Status: draft for review. Nothing here is scheduled yet.
Target: Product Hunt, Tuesday 27 October 2026, 12:01 AM PT (08:01 WAT).
Owner: Simon. Solo launch, so every task below assumes one person and one laptop.
Last verified: 17 October 2026 against the live repo, the GitHub API and the current `site/` build.

---

## 0. Readiness audit

I checked the things a launch depends on. Five are blockers, not polish.

| Check | State on 17 Oct | Verdict |
| --- | --- | --- |
| Public website | `site/` is complete but only served on `127.0.0.1:4173`. No domain, no deploy, no canonical URL. | Blocker. Product Hunt needs a live URL. |
| Root `LICENSE` | Missing. `package.json` says Apache-2.0, the README and the landing page say Apache-2.0, but GitHub's API returns `license: null`. | Blocker. The "open source" claim is unbacked on the page where people check it. |
| Default branch | `main` is 55 commits behind `upgrade/theia-1.76`. The new landing page, the V7 demo, the README rewrite and the agent panel work are only on the feature branch. | Blocker. Launch traffic lands on `main` and sees the old state. |
| Release channel | `v0.1.0-beta.3` exists with macOS arm64/x64, Windows NSIS, Linux deb and AppImage. But it is marked prerelease, so `/releases/latest` serves `v0.0.9`, a 11-day-old build. | Blocker. The newest build is not the one GitHub calls latest. |
| Audience | 1 GitHub star, 3 lifetime asset downloads across every release. | Baseline, not a blocker. Plan assumes no existing reach. |
| Installed builds | Unsigned. macOS needs right-click Open, Windows shows SmartScreen, Linux AppImage needs `chmod +x`. | Risk. Largest first-install drop-off. |
| Demo assets | 35s cut at 1920x1080 (5.2 MB) and 1080x1920 (8.1 MB), poster in both ratios. | Ready. Exists in `videos/versions/V7-35s/`, which is gitignored. |
| Share image | `site/og-image.jpg` is 1920x1080. OG and X large cards expect roughly 1200x630. | Fix. Current image will be cropped. |
| Repo metadata | `homepage` is empty. Description says everything stays on your machine, which is only true for local models. | Fix. Both are launch-facing surfaces. |
| Analytics | None on the site. None in the app by design. | Decide. Without it, launch measurement is stars and downloads only. |

The fastest path to "ready" is: add the license, merge to `main`, deploy the site to a domain, publish a non-prerelease build, set the GitHub homepage. That is one focused day, not a week.

---

## 1. Launch thesis

We are not launching "another AI coding tool". We are launching the one where the agent lives inside the editor and the loop runs on your machine.

The single sentence every asset should support:

> The agent is a panel inside the editor, not a chat window next to it. The editor and the brain run on localhost. Point it at a local model and nothing leaves the machine. Use a cloud key and only that request goes to the provider.

Three proof points carry the claim better than adjectives:

1. The plan card appears before the first write.
2. Every edited file opens as a reviewable diff.
3. The test receipt says `9 passed in 0.01s`, and it only lists rows the command actually printed.

Those are the screenshots. Everything else is context.

Why now: the build is real and cross-platform, the demo is 35 seconds, and the agent UI is finished enough to show. Waiting for signed builds or a stable 1.0 trades a launch for polish nobody sees from the outside.

---

## 2. Positioning

### The one-liner

**Undisclosed is an open source, local-first AI coding editor. The agent lives in the editor, plans before it writes, and leaves a diff and a test receipt behind.**

### Product Hunt fields

- Name: `Undisclosed`
- Tagline (60 max): `The AI coding agent lives inside your editor` (44 chars)
- Alternate: `An on-device AI coding editor with the agent inside` (51)
- Alternate: `Local-first AI coding editor. The agent is built in.` (52)
- Description (260 max): `Undisclosed is an open source, local-first AI coding editor. The agent lives in the panel, plans before it writes, and leaves a reviewable diff and a test receipt. Use a local model, DeepSeek, or your own key. Apache-2.0. No account.` (233)
- Topics: Developer Tools, Open Source, Artificial Intelligence

Pick one tagline and keep it identical everywhere: PH, X, GitHub description, press note. The name is a common English word, so always pair it with "editor" in any title or subject line. "Undisclosed editor" is the searchable phrase.

### What it is not

- Not a VS Code fork. It is Eclipse Theia, and settings, themes and Open VSX extensions import.
- Not Copilot with a new skin. The agent has shell, files, git, search, browser, screenshots and web search as selectable hands.
- Not a cloud IDE. There is no Undisclosed server and no account.
- Not free of network calls. Extensions, web search and cloud models leave the machine. Say which.

### The honest caveat, stated up front

With a local model the full loop works offline. With a cloud model, the prompt and the context the agent sends go to that provider. There is no proxy in between. That is the whole privacy story, and it is stronger than a blanket "your code never leaves your machine" because it survives scrutiny.

The current poster uses the line "code never leaves your machine". Do not put that line over footage where the model picker says DeepSeek. Either label the poster as positioning, or use a still from a local-model run for the launch gallery.

---

## 3. Audience and channels

| Segment | Where they are | What they care about | Channel |
| --- | --- | --- | --- |
| People already running local models | r/LocalLLaMA, Ollama and LM Studio communities, Hacker News | Offline loop, model support, RAM/VRAM, no telemetry | r/LocalLLaMA post, HN, Ollama Discord |
| Open source IDE and Theia people | Hacker News, GitHub, Theia community | License, architecture, plugin compatibility, packaging | Show HN, GitHub release, Theia forum |
| Privacy-sensitive engineers | X, LinkedIn | What leaves the machine, accounts, retention | X thread, LinkedIn post |
| Agent tooling builders | X, Discord servers | Hands, memory, skills, plan/diff/receipt artifacts | X thread, demo video |

Channel rules:

- Product Hunt: one listing, no "upvote for us" language anywhere. Ask for feedback, not votes. PH penalises vote solicitation and the comments are where the launch is won.
- Hacker News: one Show HN, posted by the maker, no marketing language, no emojis. Answer every technical question. Do not ask for upvotes.
- Reddit: one post in r/LocalLLaMA with the local angle. If it lands, ask the mods before cross-posting. Do not paste the same text into four subs.
- X: native video upload, link in the first reply. X suppresses the link card when a post has attached media, so do not expect a preview.
- LinkedIn: one post, the local/cloud split and the editor-native angle. No hashtag soup.

---

## 4. Pre-launch gates

T-10 is today, Saturday 17 October. The gate dates assume the 27 October launch. If a blocker slips past Friday 23 October, move the launch to Tuesday 3 November rather than shipping a broken funnel.

| Date | Gate | Done when |
| --- | --- | --- |
| Sat 17 | Plan review | This document approved, date chosen |
| Sat 17 | Add root `LICENSE` | Apache-2.0 text committed, GitHub API returns `Apache-2.0` |
| Sun 18 | Merge to `main` | `main` contains the site, V7 demo, README and beta.3; default branch is correct |
| Sun 18 | Deploy the site | Public HTTPS URL, all assets load, video plays, OG image resolves |
| Sun 18 | Domain | Registered, DNS pointed, `www` redirects, certificate valid |
| Mon 19 | GitHub metadata | Homepage set, description matches the local/cloud split, topics added |
| Mon 19 | Release channel | A non-prerelease build is latest, or the prerelease is clearly labelled on the landing page |
| Tue 20 | Clean-install test | Fresh macOS 15 arm64, Windows 11 and Ubuntu 24.04 each install and reach the agent panel |
| Wed 21 | Launch assets | Gallery, thumbnail, 16:9, 9:16 and OG all exported at spec |
| Thu 22 | Listing draft | Name, tagline, description, topics, gallery order and maker comment saved in PH |
| Fri 23 | Go / no-go | Every blocker above closed, or launch moves to 3 November |
| Sat 24 | Buffer | Fix only what the clean-install test found |
| Sun 25 | Copy freeze | No edits to tagline, description or maker comment after this |
| Mon 26 | Rehearsal | Posts scheduled, links checked, support window blocked, no code changes |
| Tue 27 | Launch | Listing live at 12:01 AM PT |

### The signing decision

Do not gate the launch on Apple notarization. It needs an Apple Developer account, a hardened runtime, entitlements and a working `electron-builder` signing path. That is days of work and a new failure surface.

Instead:

- Put the first-run instructions directly under the download button, not only in the FAQ.
- Pin an issue titled "First launch on macOS, Windows and Linux" with exact steps.
- Include checksums in the release notes.
- Say "unsigned beta" in the maker comment before anyone asks.

macOS first run: right-click the app, choose Open, then confirm. If macOS blocks it, System Settings > Privacy & Security > Open Anyway. Windows: More info > Run anyway. Linux: `chmod +x Undisclosed-*.AppImage`.

One real consequence: macOS auto-update requires a signed app. Unsigned builds will not update in place. Say that in the release notes so people do not think the updater is broken.

---

## 5. Launch assets

| Asset | Spec | Status | Action |
| --- | --- | --- | --- |
| Product Hunt thumbnail | 240x240 PNG/JPG, mark on solid background | Not exported | Export from `favicon.svg` or the 1024 mark |
| Gallery frame 1 | 1270x760, hero workspace with the panel open | Source exists (`site/demo-workspace.jpg`, 1728x1117) | Crop, do not stretch |
| Gallery frame 2 | 1270x760, plan card | Source in demo | Export clean still |
| Gallery frame 3 | 1270x760, diff card with `M app.py +7 -1` and `A test_app.py +37` | Source in demo | Export clean still |
| Gallery frame 4 | 1270x760, test receipt `9 passed in 0.01s` | Source in demo | Export clean still |
| Gallery frame 5 | 1270x760, privacy band or architecture diagram | Site has the band | Export clean still |
| Demo video 16:9 | 1920x1080, 35s, mp4, H.264, captions burned in | Ready | Copy out of gitignored `videos/` into `docs/media/` |
| Demo video 9:16 | 1080x1920, 35s | Ready | Same, for X, Reels, Shorts |
| Poster 16:9 | 1920x1080 | Ready | Use as PH video poster |
| Poster 9:16 | 1080x1920 | Ready | Use for vertical |
| OG image | 1200x630 | Current is 1920x1080 | Re-export at 1200x630 with safe margins |
| Architecture diagram | 1270x760 or inline in gallery | Site has a diagram | Export a clean version |

Gallery order matters: product first, receipts second, diagram last. Do not open with a logo card. Product Hunt visitors decide in the first two frames.

Video rules: assume autoplay with sound off. The V7 cut already burns in captions, which is why it works. Do not upload the 9:16 cut to PH; it will letterbox.

---

## 6. Listing copy

### Maker comment (paste as the first comment at launch)

> Hey Product Hunt. I built Undisclosed because I wanted an agent that works in my editor without shipping my repo to a vendor.
>
> It is Eclipse Theia, not a VS Code fork, with the agent as a native dock panel. It plans first, shows a diff per file, runs the tests it touched, and leaves the receipt in the panel. The card only lists rows the command actually printed, so a bare pass count stays a bare count.
>
> The editor and the brain run on localhost. Point it at Ollama, LM Studio or Hugging Face and the full loop works offline. If you use a cloud model, the prompt and the context the agent sends go to that provider. There is no Undisclosed server in the middle and no account to create.
>
> It is a beta. The builds are unsigned, so macOS asks you to right-click and Open the first time, and Windows shows SmartScreen. Installers for macOS, Windows and Linux are on Releases. If something breaks, file an issue and I will answer.
>
> Ask me anything about the architecture, the local/cloud split, or why the panel is not a separate window. I am watching this thread all day.

That is 190 words. It states the caveat before the audience does and gives them a reason to comment.

### Gallery captions

1. `The agent is a panel inside the editor, not a separate window.`
2. `It plans before the first write.`
3. `Every edited file opens as a reviewable diff.`
4. `It runs the tests it touched and leaves the receipt.`
5. `The editor and the brain run on localhost. Cloud is a per-model choice.`

### What not to write

- "Your code never leaves your machine" without the local-model qualifier.
- "The only outbound call is the model". Extensions and web search also leave.
- "Pings you on desktop or Slack when done". No such feature in the agent UI.
- "AI pair programmer" or "10x". The audience has read that sentence a thousand times.

---

## 7. Launch day runbook

All times PT, with WAT in brackets. 27 October 2026.

| Time | Action |
| --- | --- |
| T-24h | Final link check. Download every installer once. Confirm the site resolves without `www` and with it. Freeze code. |
| 12:01 AM (08:01) | Listing goes live. Paste the maker comment immediately. Do not edit the tagline after this. |
| 12:05 AM (08:05) | X thread. Native video on post 1. Link in the first reply, not post 1. |
| 12:20 AM (08:20) | LinkedIn post. Plain text, one link, no hashtags. |
| 1:00 AM (09:00) | Check install reports. Reply to every PH comment. |
| 3:00 AM (11:00) | Show HN goes up. Title below. First comment by the maker, technical, no pitch. |
| 3:15 AM (11:15) | r/LocalLLaMA post. Read the sub rules first, then post. |
| 5:00 AM (13:00) | Second X post: the test receipt still, one sentence. |
| 8:00 AM (16:00) | PH mid-day check. If install failures dominate, post a known-issues comment and pin it. |
| 11:00 AM (19:00) | Third X post: one architecture fact, no link. |
| 1:00 PM (21:00) | Thank-you comment on PH summarising what people asked. |
| 4:00 PM (00:00) | Capture final numbers: upvotes, comments, stars, downloads, issues. |
| 8:00 PM (04:00) | Sleep. Do not refresh the rank. |

Rules for the day:

- Reply to every comment within two hours. A specific answer beats a fast "thanks".
- Never ask for upvotes, in any channel. Ask for a try and a critique.
- When someone reports a bug, reply with the issue link, not a promise.
- Do not argue about Cursor or Copilot. Say what is different in one sentence and move on.
- Do not edit the listing description while it is live unless something is factually wrong.

---

## 8. Channel copy

### Show HN

Title: `Show HN: Undisclosed, an open-source AI code editor with the agent inside` (73)

First comment:

> I built this because I wanted an agent that works against my real workspace without a SaaS in the middle.
>
> The editor is Eclipse Theia, the agent panel is a React app served by a Theia extension, and the brain is a local FastAPI process. The two talk over localhost. The panel gets a plan before the first write, then per-file diffs, then a test receipt for the files it touched. The receipt only lists rows parsed from the command output.
>
> Model routing is per task: local via Ollama, LM Studio or Hugging Face, or BYOK for DeepSeek, Anthropic, Gemini, Mistral and OpenAI-compatible endpoints. A local model makes the loop work offline. A cloud model sends that request to the provider; there is no proxy.
>
> It is a beta and the builds are unsigned. Happy to answer architecture questions, and I would rather hear what breaks than what looks nice.

No emojis, no "excited", no link in the first comment. The title carries the URL.

### X thread

1. `Every AI coding tool asks you to move your work to it. Undisclosed runs the editor, the agent and the brain on your machine. Open source, Apache-2.0. 35 seconds of it working:` [native video]
2. `The agent is not a chat window next to the editor. It is a panel inside Theia. Cmd/Ctrl+Shift+A. It plans first, writes, runs the tests it touched, and leaves the diff.`
3. `Every change is reviewable file by file. When it edits code, it leaves a test receipt. This run: 9 passed in 0.01s. If the command does not print test names, the card does not invent rows.` [test receipt still]
4. `Models: Ollama, LM Studio or Hugging Face on your hardware. Or DeepSeek, Anthropic, Gemini, Mistral, any OpenAI-compatible endpoint with your key. Pick per task.`
5. `It is a beta. macOS builds are unsigned for now, so right-click and Open the first time. Installers and source: https://github.com/Octagon-simon/undisclosed/releases`

Do not put a link in posts 1 to 4. Do not tag influencers. Do not quote-tweet your own launch.

### r/LocalLLaMA

Title: `I built an open-source Theia editor where the coding agent runs against a local brain`

Body:

> I have been using local models for coding for a while, but the tools I tried either wanted a cloud account or parked the agent in a separate window. So I built Undisclosed: Eclipse Theia with the agent as a native dock panel.
>
> The editor and the brain run on localhost. The brain is FastAPI, the panel streams over SSE, and history and project state live under `~/.undisclosed`. With Ollama, LM Studio or Hugging Face the full plan/edit/test loop works with the network off.
>
> The part I care about: it plans before the first write, opens every edited file as a diff, and leaves a test receipt for the files it touched. The receipt only shows rows the command printed.
>
> It is a beta, builds are unsigned, and macOS needs right-click Open. I am not selling anything; the repo is Apache-2.0. I would like feedback from people running 14B to 32B models locally, especially where tool calling gets flaky. Repo and demo in the comments.

First comment: repo link and the 16:9 video. Do not include pricing, do not cross-post the same hour.

### LinkedIn

> Most AI coding tools are a chat window beside your work. Undisclosed puts the agent inside the editor, and runs the editor and the agent's brain on your machine.
>
> It plans before it writes, shows a diff for every file, and leaves a test receipt for the code it touched. Local models keep the loop offline. Cloud keys are a per-model choice, and only the request goes to the provider.
>
> It is open source, Apache-2.0, and in beta. The 35 second demo and the installers are in the first comment.

Link in the first comment, not the post. LinkedIn suppresses reach on posts with outbound links.

### GitHub release note for the launch build

Title: `v0.1.0-beta.3: the launch build`

Body: what changed since beta.2, the three install instructions, the known issues, the checksums, and one line pointing at the site. No marketing.

---

## 9. Comment playbook

| Likely question | Answer |
| --- | --- |
| Does my code leave my machine? | With a local model, no. With a cloud model, the prompt and the context the agent sends go to that provider. There is no Undisclosed server and no account. Extensions and web search can also make network calls. |
| Which models work? | Local via Ollama, LM Studio or Hugging Face. BYOK for DeepSeek, Anthropic, Gemini, Mistral and anything OpenAI-compatible. Pick per task. |
| Is it a VS Code fork? | No. Eclipse Theia. Settings, themes and Open VSX extensions import, and the import summary lists what could not. Extensions that only exist in the Microsoft marketplace are skipped. |
| Why not just use Cursor or Copilot? | Different tradeoff. This is open source, the agent is inside the editor rather than beside it, and the loop can run offline. If you want a hosted product with a polished subscription, those are better today. |
| Is it signed? | Not yet. macOS: right-click, Open. Windows: More info, Run anyway. Linux: `chmod +x` the AppImage. |
| Does auto-update work? | On Windows and Linux, yes. On macOS an unsigned build cannot update in place, so reinstall from Releases until signing lands. |
| What does it cost? | The app is Apache-2.0 and free. Cloud models are billed by the provider. |
| Does it work offline? | Editor and brain yes. The agent needs a model, so a local model is what makes the full loop work with the network off. |
| Windows and Linux? | Yes. NSIS installer, deb and AppImage are on Releases. |
| Can it open a large repo? | The agent reads files on demand and does not index the whole tree into the prompt. Very large monorepos are untested; tell me what you see. |
| Is there a team or sync feature? | No. State lives under `~/.undisclosed` on the machine. |
| What is missing? | Beta. No signing, no team sync, no hosted option, and the model picker is less polished than the editor. |
| Why the name? | Because the work stays yours. It is also a hard word to search, which is why every title pairs it with "editor". |

Answer the hostile ones plainly. "You are right, that is not signed yet" is a better reply than a paragraph of context.

---

## 10. Measurement

Baseline, verified 17 October 2026:

| Metric | Baseline |
| --- | --- |
| GitHub stars | 1 |
| Downloads across all releases | 3 |
| Open issues | 1 |
| Public site traffic | 0, site not deployed |
| Product Hunt followers | 0, no upcoming page |

Targets for launch day plus 7 days:

| Metric | Floor | Target | Stretch |
| --- | --- | --- | --- |
| PH upvotes | 80 | 250 | 600 |
| PH comments | 15 | 50 | 120 |
| GitHub stars, 7 days | 150 | 400 | 1000 |
| Release downloads, 7 days | 300 | 800 | 2000 |
| Issues filed, 7 days | 10 | 30 | 60 |
| Install success reports vs failures | 5:1 | 10:1 | 20:1 |

Because there is no analytics, the reliable signals are GitHub stars, release asset download counts and issue volume. If we add site analytics, use a privacy-respecting tool and say so on the page. Do not add an SDK to the app; "no analytics SDK in the app" is a claim worth keeping.

Capture the numbers at 12:01 AM, 8:00 AM, 1:00 PM and 8:00 PM PT on launch day, then daily for a week. Put them in one table so the retro is not guesswork.

Decision rules:

- Fewer than 50 upvotes by 8:00 AM PT: the listing is not resonating. Change the gallery order first, not the tagline.
- Install failures in more than 1 in 10 comments: publish a pinned known-issues comment and cut a patch within 24 hours.
- More than 5 requests for a signed build: start the Apple Developer enrolment the same week and say so publicly.
- A single crash reproduced twice: stop replying and fix it. The thread will wait.

---

## 11. Risk register

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| No public URL on launch day | High if not scheduled | Fatal | Domain and deploy are the first gate, not the last |
| GitHub shows no license | Certain today | High | Add root `LICENSE` before anything else |
| Traffic lands on stale `main` | Certain today | High | Merge or retarget default branch this weekend |
| Latest release is the old build | Certain today | High | Publish a non-prerelease or label the beta clearly on the landing page |
| macOS users bounce at Gatekeeper | High | High | Inline right-click instructions, pinned issue, mention in maker comment |
| Windows SmartScreen bounce | Medium | Medium | Same treatment, with a screenshot of the dialog |
| Auto-update fails on macOS | High | Medium | State it in release notes; link to a fresh download |
| Demo shows DeepSeek under a "local" poster | High | Medium | Label the model or use a local-model still for the launch gallery |
| "Your code never leaves" gets challenged | Medium | High | Use the local/cloud split everywhere; never the blanket claim |
| PH launch gets no traction | Medium | Medium | Owned channels and communities carry the day; PH is one wave, not the plan |
| Beta bugs dominate the thread | Medium | Medium | One known-issues comment, a 24-hour patch, and honest replies |
| Solo operator burns out by noon | High | Medium | Two-hour reply blocks, then step away; do not refresh rank |
| Domain name is unavailable | Medium | Low | Check today; fall back to `undisclosed.app` or `getundisclosed.com` |
| "Undisclosed" is unsearchable | Certain | Medium | Always pair with "editor"; use the phrase in titles and meta |

---

## 12. Post-launch

T+1:

- Reply to every remaining comment, including the negative ones.
- Open issues for every reproducible bug, with the reporter's name.
- Post a short thank-you with the one number that matters, not a victory lap.

T+2 to T+3:

- Cut a patch for the top three install or crash issues.
- Publish a known-issues page and link it from the README.
- If signing is now the top request, start enrolment.

T+7:

- Write a launch retro: what converted, what bounced, which channel produced the most stars per hour.
- Update the README with the install path people actually used.
- Decide whether to run a second wave (HN follow-up, a deep technical post) or stop.

T+14:

- Ship the signing work if it is still the top complaint.
- Ask the most engaged commenters for a quote or a test on their platform.

---

## 13. Decisions I need from you

1. Launch date: 27 October, or move to 3 November for more runway?
2. Domain: `undisclosed.dev` if free, or another? The site is ready to deploy as static files.
3. Merge to `main` this weekend, or make `upgrade/theia-1.76` the default branch and rename it later?
4. Signing: ship unsigned with clear instructions, or delay for notarization?
5. Product Hunt poster identity: use the existing account, or create a maker profile with a real face and bio? A face converts better on PH.
6. Analytics: leave the site unmeasured, or add a privacy-respecting counter before launch?

Until those are answered, the plan is a draft, not a schedule.

---

## Appendix: launch checklist

- [ ] Root `LICENSE` added and detected by GitHub
- [ ] `main` contains the launch build
- [ ] Site deployed, HTTPS, no `www` mismatch
- [ ] GitHub homepage set to the site
- [ ] GitHub description matches the local/cloud split
- [ ] Non-prerelease build is latest, or beta is clearly labelled
- [ ] Clean install passed on macOS, Windows and Linux
- [ ] First-run instructions on the site, release notes and a pinned issue
- [ ] Checksums published
- [ ] PH thumbnail 240x240
- [ ] PH gallery, five frames at 1270x760
- [ ] 16:9 and 9:16 videos exported and uploaded
- [ ] OG image at 1200x630
- [ ] PH listing drafted and saved
- [ ] Maker comment drafted
- [ ] Show HN title and first comment drafted
- [ ] X thread drafted, video attached natively, link only in reply
- [ ] Reddit post drafted and sub rules read
- [ ] LinkedIn post drafted
- [ ] Release note drafted
- [ ] Comment playbook open in a second window
- [ ] Two-hour reply blocks blocked in the calendar
- [ ] Metrics table created
- [ ] Go / no-go review done on Friday 23 October
