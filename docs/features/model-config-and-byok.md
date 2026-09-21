# Model configuration (BYOK) and the model picker

**Problem.** The product is bring-your-own-key and local-first: users configure
their own providers (cloud + local runtimes) instead of relying on a vendor
account. That needs a real settings surface, and the agent needs to know what each
model can do (notably: vision).

**Solution.** A model configuration screen in the panel, backed by the brain's
provider API, plus a data-driven model picker and capability gating.

---

## Configuring providers

`agent-ui/src/components/CodeAgentWorkspace/AgentModels.tsx` lets a user
add/edit/delete providers and set a default, reusing the brain's
`/api/v1/provider*` and `/model/validate` endpoints. It supports:

- **Cloud providers** with masked keys.
- **Local runtimes**: ollama, lmstudio, vllm, sglang, llama.cpp.

`AgentSettings.tsx` adds the language selector (i18n), with `get-system-language`
falling back to `navigator.language` in the embed.

## The model picker

`4efa2af` made the picker data-driven with per-row provider selection: rows come
from the configured providers rather than a hardcoded list, so a user's own models
show up and the last-used model is restored (it is persisted in `authStore`, so a
reload no longer resets new conversations to the stock model).

## Vision gating

CAMEL's `ModelType` has no vision flag, so
`brain/app/utils/model_capabilities.py::model_supports_vision()` infers it from the
model id with a conservative allowlist (`gpt-4o/4.1/5`, `claude-3/4`, `gemini`,
`qwen-vl`, `llama-4/3.2-vision`, `pixtral`, `phi-vision`, `llava`, `internvl`,
`*-vl`, ...). Unknown models are treated as text-only.

`single_agent_service.run_turn` attaches an image only when the model is
vision-capable. For a text-only model (e.g. `deepseek-chat`) it skips the ignored
image block and adds a prompt note telling the agent to read the attachment via
tools (OCR). This also stops a long OCR task from hijacking follow-up turns on
vision models, since those handle the image in one step.

See also [reasoning-and-thinking.md](reasoning-and-thinking.md): extended thinking
is requested only on the Anthropic platform.

## Where it lives

- Frontend: `agent-ui/src/components/CodeAgentWorkspace/AgentModels.tsx`, `AgentSettings.tsx`, `ChatBox/BottomBox/*` (picker), `store/authStore.ts`
- Backend: `brain/app/utils/model_capabilities.py`, the provider API under `brain/app/controller/`

## Key commits

`6f83f33` (BYOK cloud + local, settings), `4efa2af` (data-driven model picker),
`d198fc9` (API key management), plus the vision-gating work in
`model_capabilities.py`.
