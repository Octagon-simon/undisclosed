# Undisclosed — Engineering Docs

This folder explains **how the product works and why**, written for anyone who has
the repo checked out. Each doc leads with the *problem* it solves, then the design,
the code that implements it, and the honest caveats.

If you are new, read this page top to bottom, then dive into whichever system you
are touching.

---

## Systems (the core problems we solved)

These are the load-bearing systems. They answer "how does the agent understand a
codebase, remember a conversation, and not blow the token budget".

| Doc | Problem it solves |
| --- | --- |
| [systems/tree-sitter.md](systems/tree-sitter.md) | Precise, structural answers about code (`find_symbol`, `callers_of`, `context_at`) instead of guessy grep. |
| [systems/conversation-recall-and-summaries.md](systems/conversation-recall-and-summaries.md) | The agent forgets the plan between turns; recall returns fragments. Fix: a cumulative summary plus meaning-based recall. |
| [systems/memory-system.md](systems/memory-system.md) | Durable, cross-session memory: local-first store, vector facts, hybrid retrieval, scope, projects, durable jobs. |
| [systems/token-management.md](systems/token-management.md) | Keeping prompts small and cache-friendly: budgets, compaction, tool-RAG, snapshot caps, size guards. |

## Features (substantial capabilities from the git history)

Grouped by what they deliver to a user.

| Doc | Feature |
| --- | --- |
| [features/native-agent-panel.md](features/native-agent-panel.md) | The agent UI as a first-class Theia dock widget (`undisclosed-agent`), the `@undisclosed/agent-net` transport seam, and how the brain + UI were made self-contained. |
| [features/tool-rag.md](features/tool-rag.md) | Per-turn tool selection: the LLM router, atomic toolkits, `load_capability`, similarity threshold. |
| [features/reasoning-and-thinking.md](features/reasoning-and-thinking.md) | Live "Thinking…" streaming, the collapsible thinking block, and per-provider reasoning request wiring. |
| [features/browser-automation.md](features/browser-automation.md) | Standalone CDP Chromium, the live browser view, and take-control. |
| [features/connectors-and-mcp.md](features/connectors-and-mcp.md) | Local MCP connectors, the guided remote form, and the OAuth (`mcp-remote`) flow. |
| [features/model-config-and-byok.md](features/model-config-and-byok.md) | Bring-your-own-key providers (cloud + local runtimes), the model picker, and vision gating. |
| [features/hands-and-deployments.md](features/hands-and-deployments.md) | What the brain is allowed to touch, by deployment: local vs sandbox vs remote cluster. |
| [features/hooks-and-notifications.md](features/hooks-and-notifications.md) | Lifecycle hooks for external tooling (desktop notifications, automation). |
| [features/skills.md](features/skills.md) | The agent skill system and `skill-creator`. |
| [features/remote-sub-agent.md](features/remote-sub-agent.md) | Delegating a bounded task to a remote agent provider. |
| [features/editor-extras.md](features/editor-extras.md) | Source control + git extras, welcome widget, Storybook, languages/import, packaging, dev scripts. |
| [features/agent-runtime-hardening.md](features/agent-runtime-hardening.md) | The freezes, stalls, duplicate turns, and malformed-output bugs we fixed and why. |

## Design notes and plans (pre-existing)

These are the original working docs. They are more detailed than the summaries
above and are kept for history.

| Doc | What it is |
| --- | --- |
| [PACKAGING.md](PACKAGING.md) | Building/signing the desktop installers. |
| [reviews/project-context-tree-sitter.md](reviews/project-context-tree-sitter.md) | The "why" review: repomix vs tree-sitter for project understanding. |
| [reviews/grep-tool-efficiency.md](reviews/grep-tool-efficiency.md) | Findings: why `grep_files`/`search_files` are slow and unbounded, and what the output cap really covers. |
| [plans/tree-sitter-implementation-plan.md](plans/tree-sitter-implementation-plan.md) | The tree-sitter implementation plan (R1 shipped). |
| [plans/hybrid-memory-implementation.md](plans/hybrid-memory-implementation.md) | Hybrid memory module map + spec section index. |
| [rolling-conversation-summary-plan.md](../rolling-conversation-summary-plan.md) | The rolling summary plan (repo root). |
| [memory-cross-session-feature.md](../memory-cross-session-feature.md) | The cross-session memory feature spec (repo root). |
| [hybrid_memory.md](../hybrid_memory.md) | The hybrid memory spec (repo root). |
| [agents-llms-mental-model.md](agents-llms-mental-model.md) | Mental model of the agent/LLM stack. |
| [acknowledgement-gating.md](acknowledgement-gating.md) | The turn-start acknowledgement design. |
| [media-preview-and-model-picker-plan.md](media-preview-and-model-picker-plan.md) | Media preview + model picker plan. |
| [dev/assistant_message_persistence.md](dev/assistant_message_persistence.md) | Assistant message persistence notes. |

## Where things live (quick map)

```
brain/                        FastAPI agent backend ("the brain")
  app/agent/                  agent factory, prompts, tool-RAG, toolkits/
  app/memory/                 durable + semantic + hybrid memory
  app/hands/                  capability tiers (local/sandbox/remote)
  app/hooks/                  lifecycle hook dispatch
  app/remote_sub_agent/       remote delegation
agent-ui/                     React agent UI (builds to a UMD bundle)
packages/undisclosed-agent/   Theia extension that hosts the panel + proxy
packages/undisclosed-languages/, undisclosed-import/  editor extras
apps/desktop/                 Electron packaging
scripts/                      brain.sh, dev.sh, build/release
```

Environment variables are documented in the root `.env.sample` (with defaults,
commented out). Treat that file as the source of truth for knobs.
