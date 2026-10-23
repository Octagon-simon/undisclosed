# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

"""Best-effort model capability checks.

CAMEL's ModelType exposes no vision/multimodal flag (only
support_native_structured_output / support_native_tool_calling), so vision
support is inferred from the model id/name. The check is CONSERVATIVE: only
model families known to accept image input are treated as vision-capable;
everything else is treated as text-only. A false negative just means images are
routed through the tool/OCR fallback instead of native vision (still works); we
avoid false positives so we don't push image blocks at a text-only model.

"thinking" follows the same rule: it describes what THIS app can actually get
back today, not what the upstream model is theoretically capable of. That means
Anthropic extended thinking (requested in agent_model) and DeepSeek reasoning
models (emit reasoning_content without a request param). OpenAI reasoning models
are deliberately absent until reasoning_effort is wired here: tagging them would
promise a thinking block that never streams.
"""

import logging

logger = logging.getLogger("model_capabilities")

# Substrings (matched case-insensitively against the model id) that indicate a
# model family accepting image input. Keep conservative and current.
_VISION_MODEL_SUBSTRINGS: tuple[str, ...] = (
    # OpenAI
    "gpt-4o",
    "gpt-4.1",
    "gpt-4-turbo",
    "gpt-4-vision",
    "chatgpt-4o",
    "gpt-5",
    # Anthropic — Claude 3 and newer are all multimodal
    "claude-3",
    "claude-4",
    "claude-sonnet",
    "claude-opus",
    "claude-haiku",
    # Google — Gemini 1.5 / 2.x are multimodal
    "gemini",
    # Qwen vision
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "qvq",
    # Meta Llama multimodal
    "llama-4",
    "llama-3.2-11b",
    "llama-3.2-90b",
    # xAI
    "grok-2-vision",
    "grok-4",
    # Mistral
    "pixtral",
    "mistral-small-3.1",
    # Microsoft Phi
    "phi-3-vision",
    "phi-4-multimodal",
    # Other common open vision models / generic markers
    "internvl",
    "minicpm-v",
    "cogvlm",
    "llava",
    "molmo",
    "yi-vision",
    "-vl",
    "vision",
)


# Substrings that indicate a family this app can surface reasoning from.
# Anthropic: _wants_thinking requests it. DeepSeek: reasoner models return
# reasoning_content by default. Keep this list narrower than "models with a
# hidden reasoning mode" for the reason in the module docstring.
_THINKING_MODEL_SUBSTRINGS: tuple[str, ...] = (
    # Anthropic extended thinking (claude-3-7 and newer)
    "claude-3-7",
    "claude-4",
    "claude-5",
    "sonnet-4",
    "opus-4",
    "haiku-4",
    "sonnet-5",
    "opus-5",
    "haiku-5",
    # DeepSeek reasoning models. The v4 ids mirror CAMEL's
    # DEEPSEEK_THINKING_MODE_MODELS rather than a generic "v4" prefix.
    "deepseek-reasoner",
    "deepseek-r1",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "-reasoner",
)

CAPABILITY_ORDER: tuple[str, ...] = ("vision", "thinking")


def _matches(markers: tuple[str, ...], *values: str | None) -> bool:
    haystacks = [str(v).lower() for v in values if v]
    for text in haystacks:
        for marker in markers:
            if marker in text:
                return True
    return False


def model_supports_vision(
    model_platform: str | None = None,
    model_type: str | None = None,
) -> bool:
    """Return True when the given model is known to accept image input.

    Matching is on the lowercased model id (model_type), with model_platform as
    a fallback signal. Unknown models are treated as text-only.
    """
    return _matches(_VISION_MODEL_SUBSTRINGS, model_type, model_platform)


def model_supports_thinking(
    model_platform: str | None = None,
    model_type: str | None = None,
) -> bool:
    """Return True when this app can surface reasoning for the given model."""
    return _matches(_THINKING_MODEL_SUBSTRINGS, model_type, model_platform)


def model_capability_tags(
    model_platform: str | None = None,
    model_type: str | None = None,
) -> list[str]:
    """Capability tags for one configured provider row, in display order.

    Derived on read so any model the user adds is tagged without a migration.
    """
    checks = {
        "vision": model_supports_vision,
        "thinking": model_supports_thinking,
    }
    return [
        name
        for name in CAPABILITY_ORDER
        if checks[name](model_platform, model_type)
    ]
