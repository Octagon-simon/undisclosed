# Pending commit messages (scratch — delete after committing)

## `eigent` repo
Files:
- `src/agent-embed/conversation.ts` (new)
- `src/agent-embed/mount.tsx`
- `src/agent-embed/AgentEmbedPanel.tsx`
- `src/components/CodeAgentWorkspace/AgentPanelHistory.tsx`
- `src/components/ChatBox/MessageItem/PinnedPlanIndicator.tsx` (new)
- `src/components/ChatBox/MessageItem/ApprovalRequestCard.tsx`
- `src/components/ChatBox/ProjectSection.tsx`
- `src/components/ChatBox/BottomBox/InputBox.tsx`
- `src/components/ChatBox/BottomBox/PickerPanel.tsx`
- `src/lib/activityClassifier.ts`
- `src/store/chatStore.ts`

```
fix(agent-embed): replay, persistence, plan indicator, skills for the embed

Reopening a conversation showed an empty "Subtasks Planning" skeleton
instead of its messages: replay/share playback built its URL from
import.meta.env.VITE_BASE_URL, which is undefined in the embed (a prod
Vite bundle that injects endpoints at runtime), so playback 404'd and
streamed nothing.

- chatStore: build the replay/share playback URL from the injected proxy
  base (falls back to the original dev/build logic; main app unchanged).
- add createEmbedConversation(): route creation through
  createSyncedProjectInSpace (serverSynced) when a real, non-legacy Space
  is active; fall back to a local project for a blank embed. Used in
  mount.tsx bootstrap and the + New handler.
- AgentPanelHistory: refresh titles from the server when History opens
  (single-agent runs push no live title event) and pin
  lastVisitedProjectBySpace on select for exact-conversation resume.
- mount.tsx: re-hydrate the active project's chat store on folder return;
  load skills from the Brain at bootstrap (the embed had no trigger).
- PickerPanel: load skills when the skill picker opens if empty (embed
  showed an empty picker though the Brain knew the skills).
- PinnedPlanIndicator: compact, sticky plan/todo progress + checklist
  driven by the active task's taskInfo; mounted in ProjectSection.
- InputBox/ChatBox: while a task runs (and the composer is empty) the send
  button becomes a red Stop control (wired to skip-task); it flips back to
  Send when the user types a follow-up. Removed the floating Stop pill
  (FloatingAction) from ProjectSection.
- ApprovalRequestCard: show only the meaningful command (parse `command=`/
  `code=`/`query=`… out of the raw tool call) instead of the full
  tool-call signature; higher-contrast, wrapped, padded command box.
- activityClassifier: humanized activity trace is now the default
  (isActivityTraceEnabled() always true; feature flag removed) — the product
  is editor+agent. Added toolkit mappings for WebFetch ("Fetched" + url) and
  Skill ("Loaded skill"/"Listed skills"), and clearer File verbs ("Read
  file"/"Edited"/"Wrote" + filename).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

## `eigent` repo — humanized trace click-to-open + effort tuning (separate commits)
Files:
- `src/host/types.ts` (AppHost.openFile)
- `src/lib/activityClassifier.ts` (carry filePath)
- `src/components/ChatBox/MessageItem/ActivityTraceCard.tsx` (file icons + clickable filename)
- `backend/app/agent/prompt.py` (single-agent effort/skills/todo tuning)

```
feat(agent-trace): file-type icons + click-a-filename-to-open-in-editor

- AppHost.openFile(path); activityClassifier carries the full filePath;
  ActivityTraceCard shows a file-type icon and makes the filename a link
  that calls host.openFile (wired in eigent-theia to Theia's OpenerService).

fix(agent): match effort to the task (reduce tool-call overhead on small asks)

- SINGLE_AGENT_SYS_PROMPT: don't make a todo list for single-step requests;
  gate the Skills workflow to tasks that need it / reference {{skill}}; add a
  "Match effort to the task" mandatory instruction; only survey the workspace
  when discovering it (read a known file directly).
```

## `eigent` repo — plan-leak fix (separate commit)
Files:
- `backend/app/agent/factory/toolkit_assembler.py`
- `src/components/ChatBox/ProjectChatContainer.tsx`
- `src/components/ChatBox/ProjectSection.tsx`
- `.gitignore` (ignore `.todo.json` / `todo.md`)

```
fix(agent): scope the todo list per-project so plans don't leak across chats

CAMEL's TodoToolkit persists todo.md/.todo.json in working_dir and reloads
them on init. working_dir was the shared workspace FOLDER, so every new
conversation in that folder reloaded the previous project's plan.

- toolkit_assembler: store todos under ~/.eigent/todos/<project_id>/ (per
  project, and out of the user's repo).
- ProjectChatContainer: render ONE PinnedPlanIndicator for the current
  conversation's task, not one per task section.
- gitignore the todo scratch files.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

## `eigent-theia` repo
Files:
- `package.json` (webview endpoint fix)
- `packages/eigent-agent/src/browser/eigent-agent-widget.tsx` (auto-login + openFile bridge to Theia OpenerService)
- `packages/eigent-agent/src/browser/eigent-agent-layout-contribution.ts` (title theme)
- `packages/eigent-agent/assets/agent-embed/theme.css`
- `packages/eigent-agent/assets/agent-embed/agent-embed.umd.js` (synced build output)
- `packages/eigent-agent/assets/agent-embed/style.css` (synced build output)
- `scripts/dev.sh` (new)
- `.gitignore` (ignore local `.agents/`)
- removed: `packages/eigent-agent/assets/agent-embed/session.local.json` (dev-only, gitignored)

```
fix(theia): render webviews, auto-login, theme fixes + dev script

- package.json: set THEIA_WEBVIEW_EXTERNAL_ENDPOINT='{{hostname}}' (was
  '127.0.0.1:{{port}}'). Theia only substitutes {{hostname}}/{{uuid}}, never
  {{port}}, so the literal {{port}} broke webview host matching and EVERY
  webview (e.g. extension settings panels) rendered blank/black. {{hostname}}
  expands to host:port and serves webviews same-origin.
- widget: replace the static session.local.json with runtime auto-login
  (POST /api/v1/user/auto-login via the same-origin proxy) for a fresh
  local-mode token; session.local.json is now only an optional dev override.
- layout contribution: the "EIGENT AGENT" title + toolbar hover/active used
  hardcoded white; make them use Theia vars so they adapt to light themes.
- theme.css: map --ds-*-status-splitting-* and --ds-*-information-*/error-*
  token families to Theia vars so the Planning/Splitting card and the
  approval outcome boxes (approved AND denied) adapt to the active theme.
  The Approve/Deny FILLED buttons only colored on hover because Theia's host
  CSS overrode the tone class background at rest; force the PROPERTY (not just
  the token var) with scoped `.eigent-agent-root .bg-ds-bg-{success,error}-*`
  !important rules → solid green/red at rest + hover. (Stop-square red is set
  inline in the composer for the same reason.)
- .gitignore: ignore local `.agents/` (skills symlink → ~/.eigent/skills).
- Re-sync agent-embed bundle (persistence, replay-URL fix, title refresh,
  folder-switch resume, skills load, pinned plan indicator).
- Add scripts/dev.sh: start/stop/restart/build/rebuild/status/logs for the
  local Theia server (pins Node 20, waits for HTTP 200).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

## `eigent` repo — image-bleed + welcome padding (2026-08-30)
Files:
- `src/store/chatStore.ts`
- `src/components/ChatBox/ConversationWelcome.tsx`

```
fix(agent-embed): stop first-turn image bleeding into follow-up messages

Attaching an image, getting a reply, then sending a text-only follow-up
re-attached the original image to every subsequent turn — the image
reappeared in the chatbox and the agent kept re-describing it.

Root cause: the long-lived SSE "confirmed" handler built the new turn's
user-message attaches as `lastMessage.attaches` else
`[...task.attaches, ...messageAttaches]`. `messageAttaches` is the
startTask parameter captured in the closure when the FIRST message (the
image) opened the SSE consumer; that consumer never re-runs for the whole
project, so any follow-up with no new attachment fell back to the original
image. Now a follow-up with empty current attaches yields [] — only the
first (non-follow-up) confirm seeds from messageAttaches. Backend already
received improveAttaches=[] on follow-ups, so no backend change needed.

Also: make the empty-conversation welcome left-anchored (items-start /
text-left) with a px-5 gutter and full-width stacked starter buttons, so
the horizontal padding reads as a real left gutter instead of being
swallowed by centering (previous px-4/px-6 looked like no padding).
```

---

## reload-images: render + persist image attachments in the embed (2026-08-30)
`eigent` repo files:
- `backend/app/controller/file_controller.py`  (new GET /files/upload-content)
- `backend/app/service/single_agent_service.py` (confirmed event: +attaches)
- `backend/app/service/chat_service.py`          (confirmed events: +attaches)
- `src/lib/attachmentUrl.ts` (new; dual-attribution header)
- `src/components/ChatBox/MessageItem/UserMessageCard.tsx` (image thumbnails)
- `src/store/chatStore.ts` (rebuild attaches from confirmed event on replay)
- `src/components/ChatBox/ConversationWelcome.tsx` (button hover / left-anchor)

```
feat(agent-embed): show image attachments live and after reload

The embedded agent panel showed uploaded images only as file chips, and a
hard refresh lost them entirely — attaches don't round-trip through the SSE
replay, and the embed has no electronAPI to read local files.

Backend:
- Add GET /api/v1/files/upload-content?file_id=upload://<name>&session_id=<sid>
  serving an uploaded attachment's bytes inline. session_id is a query param
  because <img src> bypasses the proxy's X-Session-ID header. Path is validated
  under WORKSPACE_ROOT/<session_id>/uploads.
- Echo `attaches` on the `confirmed` SSE event (single_agent + workforce). Since
  playback re-emits the same events, this restores attaches on reload without
  any cloud history-API change.

Frontend:
- attachmentUrl.ts: resolve an upload:// ref to a served URL; isImageAttachment
  strips the `_<timestamp>` upload suffix so the real extension is read;
  deriveAttachFileName for display.
- UserMessageCard: render image attaches as inline thumbnails (click opens the
  full image); non-images keep the file chip.
- chatStore: on the confirmed event, rebuild attach objects from the echoed
  refs for the reconstructed user message (replay/reload). Priority keeps the
  live path (lastMessage.attaches) and the follow-up bleed fix intact.

Also: ConversationWelcome starter buttons size to content with a neutral
list-hover (the ds-*-hover token maps to an accent — red in some themes — and
the full-width buttons made that red span the whole panel).
```

---

## reload-images follow-ups + last-used-model persistence (2026-08-30)
`eigent` repo files:
- `src/lib/attachmentUrl.ts`        (brainEndpoint base; /files (no /api/v1) path)
- `src/store/chatStore.ts`          (backfill first replayed user msg with attaches)
- `src/store/authStore.ts`          (persist lastUsedModel)

```
fix: image thumbnails load, survive reload; persist last-used model

- attachmentUrl: build the <img> URL from brainEndpoint (not proxyEndpoint,
  which is unset in the embed -> relative URL hit the Theia host and 404'd, so
  only alt text showed) and hit /files/upload-content (the Brain serves /files/*
  with no /api/v1 prefix, matching buildRemoteFileInfoPath).
- chatStore: replay() seeds the first user message text-only and the first
  `confirmed` event is skipped, so a reloaded conversation lost its image.
  Backfill the first user message's attaches from the confirmed event's echoed
  refs (upload://) in the first-confirm branch. Live turns already carry attaches
  so the backfill no-ops for them.
- authStore: add lastUsedModel to persist partialize. It was set on model pick
  but never persisted, so a reload reset new conversations to the stock model.
```

---

## backend: agent can read + SEE uploaded image attachments (2026-08-30)
`eigent` repo files:
- `backend/app/utils/file_utils.py`            (resolve_upload_ref / resolve_attach_refs)
- `backend/app/service/single_agent_service.py`(resolve paths + vision image_list)
- `backend/app/service/chat_service.py`        (resolve additional_info paths)

```
fix(agent): resolve upload:// attaches and pass images as vision content

Attachments were handed to the agent as raw `upload://<name>` refs, which are
not real paths, so the agent couldn't open them ("path I can access"). The
upload:// resolver in the file_access layer was dead code (no callers).

- file_utils.resolve_upload_ref(): resolve upload://<stored_name> to an absolute
  path by globbing <EIGENT_WORKSPACE>/*/uploads/<stored_name>. The stored name
  is unique (ms timestamp), so no session-id plumbing is needed. resolve_attach_
  refs() maps a list.
- single_agent + workforce: resolve attaches to absolute paths before putting
  them in the prompt / camel_task.additional_info.
- single_agent run_turn: load image-typed attaches as PIL images and send them
  via BaseMessage(image_list=...) so a multimodal model actually SEES the image,
  not just its path. Non-images / unreadable files are skipped; Pillow-optional.
```

---

## backend: collapse older image attachments to text captions (2026-08-30)
`eigent` repo file:
- `backend/app/service/single_agent_service.py`

```
perf(agent): stop re-sending old image attachments every turn

An image attach is sent to the model as a vision block once (the turn it's
added), but left in agent memory it was re-encoded and re-billed on every
later turn. run_turn now calls _collapse_memory_images() at the start of each
turn: it rewrites any prior memory record whose message carries an image_list
to a text caption ("[image attachment omitted: N image(s) shown and described
earlier ...]") via dataclasses.replace + MemoryRecord.model_copy, then
clear() + write_records() (system message and order preserved). The current
turn's image is attached after this call, so it's still seen once. Best-effort:
any failure leaves memory untouched.
```

  (Update: instead of a generic placeholder, the collapse now generates a real
  2-4 sentence DESCRIPTION of the image via a one-off vision call on the agent's
  own model (_caption_images), and embeds it in the caption — so the image's
  content survives in text even if the agent never fully verbalized it. One
  caption call per image, once, when it transitions from current to old.
  Falls back to the generic marker if captioning fails.)

---

## backend: agent picks up locally-installed MCP servers (2026-08-30)
`eigent` repo file:
- `backend/app/agent/factory/toolkit_assembler.py`

```
fix(mcp): make locally-installed MCP servers reach the agent

MCPs added via the embed's Manage-connectors screen are written to
~/.eigent/mcp.json (/mcp/install), but the agent's _mcp_config only read the
request's installed_mcp, which carries just the cloud Connector Gateway
(buildConnectorGatewayMcpConfig) and is null in local mode. So a locally-added
server (e.g. @modelcontextprotocol/server-everything) never reached the agent
and its tools didn't exist.

_mcp_config now merges read_mcp_config() (~/.eigent/mcp.json) into the server
list; request-provided servers win on name clash. Applies to single-agent and
workforce. can_use_mcp gates as before (full/remote hands allow all).
```

---

## backend: vision-capability detection for image attachments (2026-08-30)
`eigent` repo files:
- `backend/app/utils/model_capabilities.py`     (new; dual-attribution header)
- `backend/app/service/single_agent_service.py` (gate image_list on vision)

```
feat(agent): only send images to vision-capable models; OCR hint otherwise

CAMEL's ModelType has no vision flag, so model_supports_vision() infers it from
the model id (conservative allowlist: gpt-4o/4.1/5, claude-3/4, gemini, qwen-vl,
llama-4/3.2-vision, pixtral, phi-vision, llava, internvl, *-vl, ...). Unknown =>
treated as text-only (falls back to the tool/OCR path, which still works).

single_agent run_turn now attaches image_list ONLY when the model is vision-
capable. For text-only models (e.g. deepseek-chat) it skips the useless/ignored
image block and adds a prompt note telling the agent to read image attachments
via tools (OCR). This also avoids the long OCR task hijacking follow-up turns on
vision models, since those handle the image in a single step.
```

---

## agent panel: reachable + brain-sourced connectors, URL MCP support (2026-08-30)
`eigent` repo files:
- `src/components/ChatBox/BottomBox/PickerPanel.tsx`     (persistent Manage footer)
- `src/components/CodeAgentWorkspace/AgentConnectors.tsx`(brain source of truth)

```
fix(connectors): keep Manage reachable; list/remove from the Brain; URL MCPs

- PickerPanel: the "Manage" action only rendered at zero items, so after adding
  a connector/skill there was no way back to the manage screen. Add a persistent
  Manage footer whenever items exist (applies to connectors and skills pickers).
- AgentConnectors: list from the Brain's /mcp/list (~/.eigent/mcp.json — the same
  config the agent reads) instead of the cloud /mcp/users, and remove via
  mcpRemove(name). Rows are keyed by server name; show a local/remote tag.
- Add flow: the cloud /mcp/import/local sync is now best-effort (the local Brain
  has no such route and it can reject remote-url shapes) — mcpInstall (writes
  mcp.json) is authoritative, so remote URL servers install reliably.
- Add form example now shows both a local command server and a remote
  streamable_http url server; helper text documents url/type: streamable_http|sse.
```

---

## connectors picker: list locally-installed (Brain) MCPs (2026-08-30)
`eigent` repo file:
- `src/components/ChatBox/BottomBox/PickerPanel.tsx`

```
fix(connectors): show Brain-installed MCPs in the composer picker

ConnectorPickerPanel listed "your MCPs" only from the cloud /api/v1/mcp/users,
so servers added via Manage connectors (which write ~/.eigent/mcp.json — esp.
remote url ones) worked when invoked but never appeared in the picker. Fetch
mcpList() (/mcp/list) alongside, map its mcpServers keys to picker items, and
merge into the "your own MCPs" group deduped by token.
```

---

## backend: defer & auto-run follow-ups sent mid-turn (2026-08-30)
`eigent` repo file:
- `backend/app/service/single_agent_service.py`

```
fix(agent): run follow-ups sent while a turn is in progress

A follow-up that arrived while a turn was running was only injected into the
live agent's memory; if the current turn finished without addressing it, it was
never answered — it looked "skipped" until the user re-sent it (repro: ask a
tool call, then send the next request before the first finished).

Now such follow-ups are DEFERRED (queued) and, as soon as the agent is idle,
run as their own normal turn (confirmed + run_turn + end). Multiple queue and
run in order. Removed the unreliable mid-run memory inject (it risked the
current turn AND the deferred turn both answering). Added _start_turn_for_improve
to share turn setup (new_task_id, model override, run_turn) between the live and
deferred paths.
```

---

## activity trace: humanize MCP connector actions (2026-08-30)
`eigent` repo files:
- `src/lib/activityClassifier.ts`
- `src/components/ChatBox/MessageItem/ActivityTraceCard.tsx`

```
feat(trace): show MCP connector actions humanized

MCP tool calls (toolkit "MCPToolkit") now get their own 'mcp' activity category:
a Plug (connector) icon + the tool name humanized (drop namespace prefix,
underscores/dashes -> spaces, Sentence-case): list_customers -> "List customers",
afriex.get_rate -> "Get rate". Added CATEGORY_NOUNS['mcp'] = connector action(s)
for the summary. We can't enumerate third-party tools, so this is a generic,
readable fallback.
```

---

## usage overview: title conversations by opening prompt (2026-08-30)
`eigent` repo file:
- `src/components/CodeAgentWorkspace/AgentUsageStats.tsx`

```
fix(usage): label conversations by first prompt, not last

The overview is per-conversation (each row = a project's total tokens + runs),
but auto-named conversations fell back to their LAST prompt, so a row was titled
by a later question and didn't match the history sidebar (which uses the opening
prompt). Request include_tasks and title by tasks[0].question (opening turn),
falling back to last_prompt then "Untitled conversation".
```

---

## backend: local tool-RAG for single-agent (per-turn tool selection) (2026-08-30)
`eigent` repo files:
- `backend/app/agent/tool_rag.py`                (new; dual-attribution header)
- `backend/app/agent/factory/single_agent.py`    (build selector, filter initial tools)
- `backend/app/service/single_agent_service.py`  (reconcile tools per turn)

```
feat(agent): tool-RAG — expose only relevant tools per turn (token cost)

Function-calling re-sends every tool schema on every LLM call; with ~15 toolkits
enabled + a connected MCP catalog that's 60-100+ schemas (tens of thousands of
tokens) per step. ToolRAGSelector embeds each tool's name+description with the
LOCAL MiniLM embeddings already used by the memory layer (chromadb Default
EmbeddingFunction), and per turn exposes only a small always-on CORE set
(file/terminal/todo/memory/human) plus the top-K tools most similar to the
user's message.

- single_agent factory builds the selector, filters the initial tool set to
  core + top-K for the opening message, and stashes it on the agent.
- run_turn reconciles the agent's live tools (add/remove) to core + top-K for
  each turn's message, so topic shifts on follow-ups get the right tools.
- Degrades safely: any failure (no embeddings, etc.) keeps ALL tools. On by
  default; EIGENT_TOOL_RAG=0 disables, EIGENT_TOOL_RAG_TOPK tunes K (default 12).
  Scoped to single-agent; the desktop workforce is untouched.
```

---

## activity trace: diff stats (+N -M) on edits (2026-08-30)
`eigent` repo files:
- `src/lib/activityClassifier.ts`
- `src/components/ChatBox/MessageItem/ActivityTraceCard.tsx`

```
feat(trace): show +N/-M line stats on edit actions

Edit rows now carry a diff {added, removed}: parsed from a unified diff for
DiffToolkit.apply_patch (the surgical-edit path; also extracts the target path
from the +++ header), or counted from a full write's content (all additions).
Added a diff-apply branch to the classifier and a green +N / red -M badge in the
trace card (explicit colors — the ds success/error text tokens map to the Theia
foreground in the embed, not green/red).
```

---

## memory settings screen: toggle + clear semantic memory (2026-08-30)
`eigent` repo files:
- `backend/app/memory/semantic_store.py`         (count/clear)
- `backend/app/controller/memory_controller.py`  (new; GET /memory/status, DELETE /memory)
- `backend/app/router.py`                         (register memory router)
- `backend/app/memory/service.py`                 (include_semantic gate)
- `backend/app/service/single_agent_service.py`   (_memory_enabled -> gate recall)
- `src/store/authStore.ts`                         (memoryEnabled + persist)
- `src/store/chatStore.ts`                         (send toolkit_config.memory.enabled)
- `src/api/brain.ts`                               (memoryStatus/memoryClear)
- `src/components/CodeAgentWorkspace/AgentMemorySettings.tsx` (new)
- `src/agent-embed/AgentEmbedPanel.tsx` + `mount.tsx`         (memory body + showMemory)

`eigent-theia` repo files:
- `packages/eigent-agent/src/browser/eigent-agent-widget.tsx`        (showMemory)
- `packages/eigent-agent/src/browser/eigent-agent-contribution.ts`   (MEMORY cmd + menu)

```
feat: memory settings screen (enable/disable + clear)

Adds a Memory screen to the embedded panel (⋯ menu -> Memory): a toggle for
semantic long-term memory and a Clear action with the stored-fact count.

Backend: semantic_store.count()/clear() (user-scoped); memory_controller with
GET /memory/status and DELETE /memory; enable flag flows as toolkit_config.
memory.enabled (mirrors governance) — the assembler already skips the memory
toolkit when off, and build_durable_context now skips semantic recall via a new
include_semantic gate (_memory_enabled reads options.toolkit_config).

Frontend: authStore.memoryEnabled (persisted); chatStore sends it in
toolkit_config; AgentMemorySettings (toggle + count + clear via /memory) reached
through a new panel body + showMemory API and a MORE-menu "Memory" item.
Memory stays local; nothing leaves the machine.
```

---

## thinking block (non-streaming, flag-gated) + memory screen UI fixes (2026-08-30)
`eigent` repo files:
- `backend/app/service/single_agent_service.py`  (_response_content returns reasoning; _thinking_enabled; end payload)
- `src/store/authStore.ts`                        (showThinking + persist)
- `src/store/chatStore.ts`                        (send toolkit_config.thinking; capture reasoning on END)
- `src/types/chatbox.d.ts`                        (Message.reasoning)
- `src/components/ChatBox/MessageItem/ThinkingBlock.tsx` (new)
- `src/components/ChatBox/UserQueryGroup.tsx`     (render ThinkingBlock above END answer)
- `src/components/CodeAgentWorkspace/AgentMemorySettings.tsx` (drop redundant title; theme-safe toggle)
- `src/agent-embed/AgentEmbedPanel.tsx` + `mount.tsx` (get/setShowThinking)

`eigent-theia` repo files:
- `packages/eigent-agent/src/browser/eigent-agent-widget.tsx`      (showThinkingEnabled/setShowThinking)
- `packages/eigent-agent/src/browser/eigent-agent-contribution.ts` (THINKING toggle cmd + menu)

```
feat: collapsible thinking block for reasoning models (flag-gated)

Capture the model's reasoning_content from the astep response
(_response_content now returns it) and include it in the 'end' SSE event when
the model produced any AND thinking is enabled (toolkit_config.thinking.enabled,
mirrors governance/memory; default on). Frontend stores it on the END Message
and renders a collapsed "Thought process" block above the answer (ThinkingBlock).
Non-streaming (v1) — shown after the turn; only appears for reasoning models
(deepseek-reasoner, o-series, Claude thinking, etc.). Toggle in the ⋯ menu
("Show thinking"), persisted in authStore.showThinking.

Also (memory screen UI): drop the redundant in-body "Memory" heading (the panel
back-bar already titles it), and make the enable toggle's off-track an explicit
translucent gray so it reads in dark mode (the ds neutral-strong token was
near-black).
```

---

## backend: cap single-agent tool-loop iterations (2026-08-30)
`eigent` repo file:
- `backend/app/agent/factory/single_agent.py`

```
fix(agent): bound the per-turn tool loop (max_iteration)

The single agent ran with max_iteration=None (unbounded), so an over-eager or
looping turn could keep calling tools forever after it had effectively
responded — the task stayed "ongoing" and had to be Stopped manually. Cap it
(EIGENT_MAX_ITERATION, default 40; 0 = unbounded) via agent.max_iteration in the
factory. CAMEL ends the turn with a "max iteration reached" result when hit.
```

---

## skills screen: compact panel-native rebuild (2026-08-30)
`eigent` repo files:
- `src/components/CodeAgentWorkspace/AgentSkills.tsx` (new)
- `src/agent-embed/AgentEmbedPanel.tsx` (mount AgentSkills instead of the full page)

```
feat(skills): compact panel-native Skills screen

Replaces the full desktop Skills page mount (hero header / wide cards / big
margins that didn't fit the narrow panel) with a compact AgentSkills: syncs
from disk, lists "Your skills" + "Examples" with an enable toggle and delete,
and adds a skill via a SKILL.md zip upload (skillImportZip). Theme-safe toggle
(same fix as the memory screen). Bundle got slightly smaller by dropping the
full-page import.
```

---

## managed screens: Back-only header, no box border, real toggle colors (2026-08-30)
`eigent` repo files:
- `src/agent-embed/AgentEmbedPanel.tsx` (ManagedScreen: Back-only, drop border-b)
- `src/components/CodeAgentWorkspace/AgentMemorySettings.tsx` (re-add title; toggle colors)
- `src/components/CodeAgentWorkspace/AgentSkills.tsx` (toggle colors)

```
fix(embed): clean up the managed-screen header + switch colors

- ManagedScreen now shows just "‹ Back" (no per-screen title) and drops its
  border-b. Each screen (Memory/MCP connectors/Skills) already renders its own
  title row, and the panel toolbar has a divider, so the extra bordered header
  read as a heavy "box" around the row. Re-added the "Memory" title to its
  screen since Back no longer carries it.
- Switch pills: on=#22c55e / off=#6b7280 explicit colors. The ds
  brand-default-default token is UNMAPPED in the embed theme, so
  `background: var(--ds-bg-brand-default-default)` resolved to nothing and the
  "on" pill rendered black in dark mode. Same fix for the Memory + Skills toggles.
```

---

## fix diff-in-trace parsing (escaped newlines from repr narration) (2026-08-30)
`eigent` repo file:
- `src/lib/activityClassifier.ts`

```
fix(trace): count diff lines from the repr-narrated tool input

The backend narrates tool args as key=repr(value), so newlines arrive as the
literal escape `\n` (backslash-n), not real newlines — so splitting on \n
counted every write/patch as a single line and no +N/-M ever showed. Add
splitLines() that splits on both `\n` and real newlines; use it in countDiffLines
and the write-content count. (Very large content is still truncated by the
narration; a backend stat-emission would make big diffs exact — follow-up.)
```

---

## diff-in-trace: emit line count from write narration + prefer file tools (2026-08-30)
`eigent` repo files:
- `backend/app/agent/toolkit/file_write_toolkit.py` (write_to_file narration -> [diff +N -0])
- `backend/app/agent/prompt.py`                     (use file tools, not shell, for edits)
- `src/lib/activityClassifier.ts`                   (parse [diff +N -M] tag)

```
fix(trace): make write_to_file emit its line count for the diff badge

write_to_file's listen narration was a fixed string that OMITTED the content
("write content to file: X ..."), so the frontend had nothing to count and no
+N badge ever showed. The narration now appends a machine-readable "[diff +N -0]"
tag (N = content line count); the classifier parses that tag first (most reliable
vs. the truncated/omitted raw content). apply_patch keeps default patch narration
(escaped-newline parsing handles it, modulo truncation).

Also (prompt): instruct the single agent to CREATE/EDIT files with write_to_file
/ apply_patch, NOT shell (echo>/cat<<EOF/sed -i), so changes are tracked and
visible in the diff badge + editor source control.
```

---

## editor: add git + Source Control; classify terminal file-writes; Cmd+A guard (2026-08-30)
`eigent-theia` repo:
- `package.json` (+ @theia/git, @theia/scm, @theia/scm-extra @1.60.0)

`eigent` repo:
- `src/lib/activityClassifier.ts` (write_content_to_file -> edit + diff)
- `src/agent-embed/mount.tsx` (Cmd/Ctrl+A capture guard for panel inputs)

```
feat(editor): add git Source Control; fix diff for terminal writes; local Cmd+A

- eigent-theia: bundle @theia/git + @theia/scm + @theia/scm-extra. The product
  had no SCM provider ("no repo found" even in a git repo). Now the workspace
  shows Source Control (A/M/U), click-to-diff, and the editor dirty-diff gutter,
  using system git. (Web Theia does git fine — the extensions were just missing.)
- activityClassifier: TerminalToolkit.shell_write_content_to_file is a real file
  write (not a shell command) but lives on the terminal toolkit, so it was
  bucketed as "shell" (verb "Ran", no diff). Classify any write_to_file /
  *write*content* method as an edit (verb "Wrote") with the +N diff, before the
  shell branch.
- mount: Cmd/Ctrl+A fired Theia's global editor select-all even when a chatbox
  input was focused. A window-capture guard stops propagation for A when the
  target is one of the panel's inputs, so the browser selects the input's text
  and Theia never sees it.
```

---

## fix: open generated/output files in the Theia editor from chat (2026-08-30)
`eigent` repo file:
- `src/components/ChatBox/UserQueryGroup.tsx`

```
fix(embed): open file chips in the editor instead of a no-op preview

The output-file chips (and END fileList items) called usePageTabStore.
openFilePreview — a desktop-only page-tab preview that isn't mounted in the
embed, so clicking did nothing. Route through host.openFile(file.path) when
available (opens the real file as a Theia editor tab; handles absolute/relative
paths), falling back to the page-tab preview on desktop.
```

---

## chat: clickable file paths + end-of-task "Files changed" summary (2026-08-30)
`eigent` repo files:
- `src/components/ChatBox/MessageItem/MarkDown.tsx` (clickable path code-spans + host.openFile)
- `src/lib/activityClassifier.ts` (extractChangedFiles / ChangedFile)
- `src/components/ChatBox/MessageItem/FilesChanged.tsx` (new)
- `src/components/ChatBox/UserQueryGroup.tsx` (render FilesChanged in END branch)

```
feat(chat): clickable file paths + files-changed summary at task end

- MarkDown: absolute file paths written in `code` spans (e.g. "saved at
  `/Users/.../x.html`") are now clickable and open in the Theia editor via
  host.openFile; file-path clicks (links or code spans) route through
  host.openFile in the embed (page-tab preview is the desktop fallback).
- FilesChanged: end-of-task summary listing the files the agent wrote/edited
  (extractChangedFiles aggregates edit-category tool calls across the task's
  agent logs, deduped by path, carrying the +N/-M diff). Each row opens the
  file in the editor. A lightweight take on Antigravity's changed-files list;
  line-by-line accept/reject is tracked as a separate, larger task.
```

---

## activity trace: colored file-type badges + fix search display (2026-08-30)
`eigent` repo files:
- `src/components/ChatBox/MessageItem/ActivityTraceCard.tsx` (colored file-type badges)
- `src/lib/activityClassifier.ts` (search/grep/glob: read pattern=, not just query=)

```
feat(trace): Antigravity-style file-type badges; readable search rows

- FileTypeIcon is now a small colored rounded badge with a short label in the
  language's brand color (TS #3178c6, JS, PY, JSON, MD, CSS, HTML, Go, Rust, …),
  special-casing package.json -> "npm", README -> info, Dockerfile, .env. Images
  keep the image glyph.
- Search rows were garbled ("Searched Do…") because file/code search tools pass
  pattern= (not query=). Read pattern/regex/keyword/text too; classify grep/glob
  as search; glob shows "Found files". No more raw-arg dumps in the trace.
```

---

## remove max_iteration cap; outlined file-type badges (ts != tsx) (2026-08-30)
`eigent` repo files:
- `backend/app/agent/factory/single_agent.py` (max_iteration default -> unbounded)
- `src/components/ChatBox/MessageItem/ActivityTraceCard.tsx` (outlined badges)

```
fix: remove max_iteration cap; outlined file badges, distinct ts/tsx

- max_iteration now defaults to UNBOUNDED (0). A 40-cap truncated legit long
  tasks and left a dangling "Let me look at…" non-answer as the final response;
  the real "runs forever" case is handled by the deferred-follow-up fix, not
  this blunt cap. Re-enable via EIGENT_MAX_ITERATION=<N>.
- File-type badges are now OUTLINED (transparent fill, colored border + label)
  instead of solid blocks, and ts/tsx (and js/jsx) are distinct (TS vs TSX,
  React cyan). Longer labels (JAVA, YAML, SCSS) allowed.
```

---

## prompt: never edit build artifacts, edit source (2026-08-30)
`eigent` repo file:
- `backend/app/agent/prompt.py`

```
prompt(agent): general "edit source, not build artifacts" rule

Added a global mandatory instruction: don't modify generated/compiled output
(*.min.js/*.umd.js/*.bundle.js, dist/build/out/.next/coverage, node_modules,
lockfiles) — they're overwritten on the next build and searching minified
output balloons tool calls; find and edit the source (or ask). General
principle (applies to any project), not eigent-specific.
```

---

## prompt: answer the current message, don't re-run completed tasks (2026-08-30)
`eigent` repo file:
- `backend/app/agent/prompt.py`

```
prompt(agent): prioritize the current message; don't redo finished work

Weak/text-only models fixate: given a conversational or follow-up message
("it said this…", "I just did"), they re-execute a COMPLETED prior task
(re-running scripts, rewriting the same file) instead of answering. Added a
mandatory rule: the history/previous task is context, not a to-do list — respond
to the CURRENT message, never repeat a prior answer verbatim or redo finished
work unless explicitly asked; ask a short clarifying question if unsure. A better
model already does this; the rule nudges weaker ones.
```

---

## embed theme: map brand tokens; fix welcome logo in dark (2026-08-30)
`eigent` repo file:
- `src/components/ChatBox/ConversationWelcome.tsx` (explicit logo colors)
`eigent-theia` repo file:
- `packages/eigent-agent/assets/agent-embed/theme.css` (map --ds-*-brand-* tokens)

```
fix(embed): map unmapped brand tokens; welcome logo visible in dark

The --ds-*-brand-* tokens (bg/icon/text/border) were never mapped in the embed
theme, so every brand-colored element resolved to nothing -> black/invisible in
dark mode (welcome logo, primary buttons, "on" toggles). Map them to explicit
violet brand values (read on both themes) in theme.css — the systemic fix so we
stop pinning per-element. Also pinned the welcome logo badge colors directly.
```

---

## prompt: reuse project understanding on follow-ups (2026-08-30)
`eigent` repo file:
- `backend/app/agent/prompt.py`

```
prompt(agent): build on existing project understanding, don't re-crawl

For follow-up questions in an already-explored project, reuse the cached
understand_project digest + earlier findings and do a few TARGETED lookups
(grep the specific list/config), instead of re-exploring the whole codebase.
Weak/small-context models trim the overview and re-crawl (the 39-command
pattern); this biases toward reuse.
```

---

## fix plan-regression live; make understand_project always available (2026-08-30)
`eigent` repo files:
- `src/store/chatStore.ts` (END: promote leftover subtasks -> completed)
- `backend/app/agent/tool_rag.py` (project_context + search are core)

```
fix(plan): promote leftover todos to completed on live task end

The pinned plan showed "incomplete" for a finished task until reload — because
polishCompletedHistoryTask (promote non-terminal subtasks -> COMPLETED) only ran
on refresh. Apply the same promotion LIVE in the END handler (skip user-stopped
runs; keep FAILED visible), so the plan reads complete immediately. Confirmed on
gemini, so it was a state bug, not a model artifact.

tool-RAG: make Project Context Toolkit (understand_project) + Search core/always-
available, so the agent can hit the cached repo digest instead of blind-grepping
a project it already explored (15x "country" searches). Pairs with the reuse-
project-understanding prompt.
```

---

## picker panel: soften the heavy border (connectors + skills) (2026-08-30)
`eigent` repo file:
- `src/components/ChatBox/BottomBox/PickerPanel.tsx`

```
fix(embed): subtle picker border instead of the prominent panel-border box

The composer connector/skill picker used border-ds-border-neutral-default-default,
which maps to Theia's panel-border — a heavy grey box (both border tokens map to
the same thing, so swapping didn't help). Replace with a translucent hairline
(rgba(127,127,127,0.22)) + shadow-lg for lift; reads on light and dark. Applies
to both pickers (shared component).
```
  (update: removed the border ENTIRELY like the Back-header fix + pinned an explicit
  box-shadow for popover lift, since the ds/shadow-perfect var chain was unreliable.)

---

## reload: render agent-output images in the embed (2026-08-30)
`eigent`: `src/host/types.ts`, `src/components/ChatBox/MessageItem/MarkDown.tsx`
`eigent-theia`: `packages/eigent-agent/src/browser/eigent-agent-widget.tsx`, `package.json`

```
feat(embed): render agent-output images in the Theia agent panel

Agent-output images referenced by path in markdown fell back to "[alt]" in the
embed because the renderer only read bytes via Electron's readFileAsDataUrl
(null outside desktop). Add an optional host.readFileAsDataUrl seam and
implement it in the Theia widget via FileService (resolve relative paths against
the workspace root, encode as a data URL).
```

## browser take-control: CDP screencast + input bridge (2026-08-30)
`eigent`: `backend/app/controller/browser_stream_controller.py`, `backend/app/router.py`,
`src/components/BrowserAgentWorkspace/BrowserTakeControl.tsx`, `src/agent-embed/*`
`eigent-theia`: widget + contribution (globe toolbar button)

```
feat(browser): live agent-browser view + take-control in the Theia panel

Backend /browser/stream WebSocket speaks raw CDP over websockets+httpx (no
python-playwright dep): discover the page target, attach a second DevTools
client, force a render surface with Emulation.setDeviceMetricsOverride (the
agent's window is offscreen so it composites nothing otherwise), Page.start-
Screencast -> relay frames, forward mouse/keyboard as Input.dispatch*. Frontend
BrowserTakeControl renders frames to a canvas; "Take control" forwards input and
pauses the agent via the existing /take-control. DPR-aware, quality 85.
```

## tool-RAG: atomic toolkits + browser always-on (2026-08-30)
`eigent` + `eigent-theia/brain`: `app/agent/tool_rag.py`

```
fix(tool-rag): atomic toolkit selection + keep the Browser Toolkit always-on

The agent claimed it "can't browse" and punted to the default browser because
tool-RAG exposed only per-turn top-K tools and the Browser Toolkit fell out of
the cut. Expose a whole toolkit when any of its tools is relevant, and mark
browsing core (always available).
```

## prompt + service: stop reiteration & confabulation (2026-08-30)
`eigent` + `eigent-theia/brain`: `app/service/single_agent_service.py`, `app/agent/prompt.py`

```
fix(agent): stop reiterating completed tasks + confabulating take-control

Sharply delimit the current message ("respond to THIS", accept corrections),
label history as completed-background, inject a grounding memory on take-control
resume (the user drove the browser; don't invent steps/PINs), and add prompt
rules against fabricating credentials/confirmations.
```

## model configuration (BYOK) panel + settings + host no-ops (2026-08-31)
`eigent`: `src/components/CodeAgentWorkspace/{AgentModels,AgentSettings}.tsx`,
`src/agent-embed/*`, `src/store/chatStore.ts`, `src/components/ChatBox/MessageItem/UserMessageCard.tsx`
`eigent-theia`: widget + contribution (Models, Settings menu items), `theme.css`

```
feat(embed): model config (BYOK cloud+local), language settings, host fallbacks

AgentModels: add/edit/delete providers + set default (cloud providers and local
runtimes ollama/lmstudio/vllm/sglang/llama.cpp), reusing /api/v1/provider* and
/model/validate; keys masked. AgentSettings: language selector (i18n). Map the
unmapped success-subtle token so Default/Live badges theme correctly. Route
reveal-in-folder -> host.openFile and get-system-language -> navigator.language
in the embed.
```

## brain: vendor the backend into eigent-theia (2026-08-31)
`eigent-theia`: `brain/**` (copied), `scripts/{setup-brain,brain}.sh`, `scripts/dev.sh`, `.gitignore`

```
feat(brain): vendor the agent backend into eigent-theia (self-contained)

Copy eigent/backend -> brain/ and run it via its existing standalone mode
(python main.py, uvicorn :5001) against an eigent-theia-owned uv venv. Add
scripts/setup-brain.sh (uv sync) and scripts/brain.sh (start/stop/logs); dev.sh
now brings up both Theia and the brain. eigent-theia no longer needs the eigent
desktop app to run the agent.
```

## brain: launch own Chromium in standalone mode (2026-08-31)
`eigent-theia/brain`: `app/agent/factory/toolkit_assembler.py`, `app/utils/browser_launcher.py`

```
fix(brain): launch a CDP Chromium standalone (Electron no longer provides one)

The desktop app used to provide the CDP browser via Electron; the standalone
brain had none, so browser tools failed and the agent silently fell back to the
MCP. Call ensure_cdp_browser_endpoint when no hands/EIGENT_CDP_URL provide a
browser, and teach _find_chrome_executable to discover the Playwright browser
cache (ms-playwright) + an EIGENT_CHROME_PATH override. Uses a persistent
profile so logins survive.
```

## guard: don't silently swap tools / remove auth (2026-08-31)
`eigent-theia/brain`: `app/agent/prompt.py`

```
fix(agent): surface tool failures instead of silently switching or faking

If a needed tool is unavailable/fails (browser can't start, connector down,
credential missing), STOP and tell the user which tool failed and the options —
don't silently switch to a different method (e.g. API/MCP when asked for the
browser) or fabricate a key/token/result. Also: never log out or clear a stored
session as "cleanup" unless asked.
```

## ui: vendor the agent UI source into eigent-theia (2026-08-31)
`eigent-theia`: `agent-ui/**` (copied), `package.json` (build:agent-ui, sync), `scripts/dev.sh`

```
feat(ui): vendor the agent UI source into eigent-theia (builds in-repo)

Copy eigent/src + build configs + package.json -> agent-ui/ and build the
embeddable UMD bundle there (npm run build:agent-ui -> vite lib build -> sync
into packages/eigent-agent/assets). sync:agent-bundle no longer reaches into
../eigent; dev.sh build refreshes the panel bundle too. Combined with the
vendored brain, eigent-theia builds AND runs the whole agent product on its own.
```

## connectors: guided remote-MCP form (URL + transport) (2026-08-31)
`eigent-theia/agent-ui`: `src/components/CodeAgentWorkspace/AgentConnectors.tsx`

```
feat(connectors): guided "remote server" form with transport picker

Add a Guided tab to the MCP connectors screen: name + server URL + transport
(Streamable HTTP / SSE / OAuth). OAuth generates an mcp-remote bridge config
(command: npx mcp-remote <url>) which runs the browser OAuth flow and caches the
token in ~/.mcp-auth; Streamable HTTP / SSE connect directly with an optional
Bearer token. The raw "Paste JSON" mode remains behind the second tab.
```
  (follow-up fix: the Connectors panel went blank — installGuided's useCallback
  referenced `load` before its declaration (temporal dead zone) → ReferenceError
  at render. Moved installGuided/resetForms below `load`.)

## chore: dual-attribution license headers (2026-08-31)
`eigent-theia/agent-ui` + `eigent-theia/brain`: files with substantial 2026 contributions

```
chore(license): add Simon Ugorji portions copyright to modified files

Add "Portions Copyright 2026 Simon Ugorji. All Rights Reserved." beneath the
Eigent Apache-2.0 banner on the existing files substantially changed this cycle
(agent-ui: MarkDown, UserMessageCard, AgentEmbedPanel, mount, chatStore; brain:
single_agent_service, prompt, toolkit_assembler, browser_launcher, router).
Eigent's copyright + NOTICE are preserved as Apache-2.0 requires. New files
already carried the dual header.
```

## connectors: local-only picker + OAuth Authenticate button (2026-08-31)
`eigent-theia/agent-ui`: `PickerPanel.tsx`, `AgentConnectors.tsx`, `api/brain.ts`
`eigent-theia/brain`: `app/controller/mcp_controller.py`

```
feat(connectors): local-only picker + one-click OAuth authenticate

Standalone product: the composer connector picker now lists ONLY local MCP
servers (mcp.json) — the same list as Manage Connectors — instead of also pulling
Eigent's hosted/cloud account connectors (:3001). Kills the confusing "4 vs 3"
and drops an external dependency.

Add an "Authenticate" button on OAuth (mcp-remote) connector rows: POST
/mcp/authenticate runs `mcp-remote <url>` interactively (outside the agent's
timeout-bounded task connection), opens the browser for sign-in, and resolves
once the token is cached under ~/.mcp-auth — so the human can actually complete
the OAuth consent. Rows are tagged oauth/remote/local accordingly.
```

## connectors: surface the real OAuth failure reason (2026-08-31)
`eigent-theia/brain`: `app/controller/mcp_controller.py`

```
fix(connectors): report the real mcp-remote OAuth error to the user

The /mcp/authenticate endpoint sent mcp-remote's output to /dev/null, so a
failure looked like "nothing happened". Capture its output and return the actual
error — and for the common "does not support dynamic client registration" case
(e.g. Asana), return actionable guidance (use a Personal Access Token via
Streamable HTTP, or register an OAuth app).
```

## connectors: OAuth with pre-registered client (Asana) (2026-08-31)
`eigent-theia/agent-ui`: `AgentConnectors.tsx`
`eigent-theia/brain`: `app/controller/mcp_controller.py`

```
feat(connectors): support OAuth MCPs that need a pre-registered client

Asana (and similar) don't allow dynamic client registration, so mcp-remote
needs a client_id/secret. The guided OAuth form now collects Client ID/Secret
and pins a stable callback port (33418), generating
`mcp-remote <url> 33418 --static-oauth-client-info {client_id,client_secret}`
and showing the redirect URI to register. The /mcp/authenticate endpoint now
runs the connector's FULL configured command+args (not just the bare URL), so
the static client info is actually used and the browser OAuth can complete.
```

## embed: mount the Toaster (toasts were silent) (2026-08-31)
`eigent-theia/agent-ui`: `src/agent-embed/mount.tsx`

```
fix(embed): mount the sonner Toaster so toasts actually show

The Toaster was only mounted in the desktop App.tsx; the embed renders
AgentEmbedPanel directly, so EVERY toast (errors, "connector added", auth
results, …) was invisible — failures looked like "nothing happened". Mount
<Toaster/> in the embed entry, portaled to <body> at a high z-index.
```

## connectors: fix stale client id/secret in OAuth install (2026-08-31)
`eigent-theia/agent-ui`: `AgentConnectors.tsx`

```
fix(connectors): include OAuth client id/secret (stale useCallback deps)

installGuided's dependency array omitted gClientId/gClientSecret, so the
callback captured their initial (empty) values — the entered Client ID/Secret
were never written into the mcp-remote config, and Asana OAuth kept failing.
Add them to the deps.
```

## connectors: fix OAuth success detection (false negative) (2026-08-31)
`eigent-theia/agent-ui`: `AgentConnectors.tsx` (redirect URI: localhost not 127.0.0.1)
`eigent-theia/brain`: `app/controller/mcp_controller.py`

```
fix(connectors): detect mcp-remote OAuth success from its output

Two fixes: (1) the guided form advertised the redirect URI as 127.0.0.1, but
mcp-remote registers http://localhost:<port>/oauth/callback — Asana rejected the
mismatch. (2) The authenticate endpoint reported success only if a NEW token file
appeared, but a re-auth reuses the cached token (deterministic filename) and
mcp-remote stays running on success, so it looked like a failure. Detect success
from mcp-remote's output ("Proxy established" / "Connected to remote server") and
surface real "Fatal/Connection error" lines otherwise.
```

## connectors: reflect authenticated state on the button (2026-08-31)
`eigent-theia/agent-ui`: `AgentConnectors.tsx`

```
feat(connectors): show "Authenticated" state after OAuth sign-in

After a successful Authenticate, the row's button turns green "Authenticated"
(check icon) instead of a plain "Authenticate" — still clickable to re-auth if a
token expires. Tracked per session.
```

## brain: auto-restart supervisor + preserve crash log (2026-08-31)
`eigent-theia`: `scripts/brain.sh`, `.gitignore`

```
fix(brain): auto-restart on crash + keep the previous log

The brain dropping wiped in-memory task state (conversations reloaded with "No
steps found") and truncated .brain.log on restart (crash reason lost). Wrap the
server in a supervisor loop gated by .brain.run: on an unexpected exit it
snapshots .brain.log.prev and respawns after 2s; `stop` removes the runfile so
it exits cleanly. Verified auto-restart after a kill.
```

## git: extra developer commands (undo last commit, etc.) (2026-08-31)
`eigent-theia`: `packages/eigent-agent/src/browser/git-extras-contribution.ts` (new),
`eigent-agent-frontend-module.ts`, `package.json` (@theia/git dep)

```
feat(git): add Undo Last Commit + unstage/discard-all commands

Theia already ships the full SCM stack (source control view, stage/unstage/
commit/amend, merge editor, dirty-diff, stash, pull/push/sync, history). Fill the
gaps developers expect with a GitExtrasContribution using the Git service:
"Undo Last Commit (keep changes)" = reset --soft HEAD~1, "Undo Last Commit
(discard changes)" = reset --hard HEAD~1 (confirmed), "Unstage All" = reset,
"Discard All Changes" = checkout -- . (confirmed). Available in the command
palette and a Git main-menu. Needs a full theia build.
```

## tool-rag: browser retrievable (not always-on) to cut input tokens (2026-08-31)
`eigent-theia/brain`: `app/agent/tool_rag.py`

```
perf(tool-rag): make the Browser Toolkit retrievable, not core

Browser was pinned always-on (17 tool schemas every turn) as a belt-and-suspenders
after the "can't browse" bug — but that predates atomic-toolkit retrieval, which
now reliably surfaces the WHOLE browser toolset when a browse query scores. Move
it out of core to save ~17 tool schemas per non-browsing turn. Set
EIGENT_BROWSER_ALWAYS_ON=1 to pin it back if browsing ever isn't retrieved.
```

## observability + dynamic tools + auth persistence (2026-08-31)
`eigent-theia/brain`: `app/agent/listen_chat_agent.py`, `app/agent/tool_rag.py`,
`app/agent/factory/single_agent.py`, `app/controller/mcp_controller.py`
`eigent-theia/agent-ui`: `api/brain.ts`, `AgentConnectors.tsx`

```
feat(agent): usage breakdown logging + load_capability meta-tool

- [USAGE] per-request log line: input/cached/output/total tokens (+ cache %),
  across OpenAI/Anthropic/Gemini usage formats. Makes the input-heavy agentic
  cost visible and shows whether prompt caching is landing — before deciding to
  wire explicit caching.
- load_capability meta-tool: the agent can attach a whole toolkit on demand
  mid-task (CAMEL rebuilds tool schemas each iteration, so it's usable next
  step). Its <loadable_capabilities> catalog is injected into the system prompt.
  Additive to per-turn tool-RAG; degrades safely.
```

```
feat(connectors): persist "Authenticated" across reloads

Record OAuth-completed connectors in ~/.eigent/mcp_authed.json on success; add
GET /mcp/auth-status (filtered to servers still in the config) and load it in
AgentConnectors so the button shows Authenticated after a reload.
```

## tool-rag: relevance threshold to stop over-exposing tools (2026-08-31)
`eigent-theia/brain`: `app/agent/tool_rag.py`
`eigent-theia`: `scripts/dev.sh`

```
perf(tool-rag): similarity threshold so trivial messages expose only core

[USAGE] instrumentation revealed "hii" sent 101/145 tool schemas = ~50K input
tokens (0% cached): atomic-toolkit expansion over-fired on weak embedding
matches. Add EIGENT_TOOL_RAG_MIN_SCORE (default 0.10, calibrated from real
MiniLM scores): a tool must clear the bar before it (and its toolkit) attach.
"hii"/"hello" (~0.06-0.09) -> core only; "go to <url> and log in" (~0.11) and
clearer intents still match; the load_capability meta-tool covers anything below.

dev.sh: guard each build step (❌ markers), and rebuild ALWAYS restarts Theia +
brain even if the build errors (⚠️) so a bad build can't leave you backend-less.
```

## tool-rag: LLM capability router (2026-08-31)
`eigent-theia/brain`: `app/agent/tool_rag.py`, `app/service/single_agent_service.py`

```
feat(tool-rag): LLM router decides which capabilities to attach

Per turn, an LLM router picks the toolkits a task needs from a COMPACT catalog
(toolkit name + sample tool names — not schemas), reusing the agent's own model
via a throwaway, memory-isolated ChatAgent. The main agent then gets the full
schemas of only the chosen toolkits + core. This replaces the blunt embedding
score for the DECISION (an LLM tells "hello" from "go to afriex and log in");
the embedding threshold remains the fallback on router failure, and
load_capability covers mid-task needs. Toggle via EIGENT_TOOL_ROUTER=0.
```

## tool-rag: cap per-toolkit tools + anti-flailing prompt (2026-08-31)
`eigent-theia/brain`: `app/agent/tool_rag.py`, `app/agent/factory/single_agent.py`, `app/agent/prompt.py`

```
perf(agent): cap huge MCP toolkits + discourage redundant tool calls

[USAGE] showed a task hit 60K input/step because load_capability(MCPToolkit)
dumped ~40K of Asana tool schemas (30 tools, huge params) into context, re-sent
every step at 0% cache, while the agent made 14 near-duplicate Asana calls.
- Cap tools attached per toolkit to the most-relevant N (EIGENT_TOOL_RAG_MAX_PER_
  TOOLKIT=12), ranked by query similarity — in both the embedding path and the
  router/load_capability path. A 30-tool MCP now contributes 12, not 30.
- Also start the agent lean (core only); per-turn router adds the rest.
- Prompt: be economical with tool calls; don't brute-force parameter variations.
```
