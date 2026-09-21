# Reasoning and thinking

**Problem.** Reasoning models stream their chain of thought separately from the
answer. We wanted to (a) *show it live* so the user sees progress instead of a
spinner, and (b) never let it pollute the final answer.

**Solution.** Stream `reasoning_content` deltas to the UI as they arrive, render a
live "Thinking..." block, and store the reasoning for a collapsible block on the
finished message.

---

## Streaming the reasoning

`brain/app/service/single_agent_service.py` reads `reasoning_content` deltas off
each streamed chunk and pushes them as `Action.reasoning` SSE events. The UI
renders them live in a `LiveReasoning` block while the turn runs. A
`_is_meaningful_reasoning` filter drops noise so empty/whitespace deltas do not
flicker the block.

Commit `4f168ee` ("live reasoning streaming") introduced this.

## The collapsible thinking block

`agent-ui/src/components/ChatBox/MessageItem/ThinkingBlock.tsx` renders a
collapsed "Thought process" block above the answer on the finished message. It is
flag-gated by a `showThinking` toggle (persisted in `authStore`, reached through
the panel's MORE menu). The non-streaming v1 version captures the reasoning from
the `astep` response and includes it in the `end` SSE event.

## Requesting reasoning per provider (the honest part)

There is an important asymmetry to know about:

- **Anthropic** is the only provider where we *request* extended thinking. In
  `brain/app/agent/agent_model.py` the injection is guarded by
  `if _mp == ModelPlatformType.ANTHROPIC`: it injects
  `{"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}}`
  (Claude 5+, default) or `{"type": "enabled", "budget_tokens": N}` (older
  models, opt-in via `UNDISCLOSED_THINKING_TYPE=enabled`), forces `temperature=1`,
  strips `top_p`/`top_k`, and bumps `max_tokens`.
- **OpenAI and DeepSeek** are not wired to *request* reasoning. The code comment
  is explicit ("other providers are left untouched until their param is wired").
  The streaming/reading half is provider-agnostic, so a model that already emits
  `reasoning_content` (e.g. `deepseek-reasoner`) shows its thinking, but nothing
  in the brain asks for it on those platforms. `deepseek-chat` will not emit any.

If you want OpenAI (`reasoning_effort` / `max_completion_tokens`) or DeepSeek
reasoning, that is a real, unshipped gap: add a branch to the injection block in
`agent_model.py` mirroring the Anthropic one.

## Related

The `[USAGE]` logging in `listen_chat_agent.py` also normalizes cached-input
metrics, which matters for reasoning models because their cached prefix is large.
See [../systems/token-management.md](../systems/token-management.md).

## Key commits

`4f168ee` (live reasoning streaming + Figma toolkit), `d48e396` (collapsible
thinking block, flag-gated), `1c8af50` (thinking display + release prep).
