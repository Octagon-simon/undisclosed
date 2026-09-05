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

import logging
import uuid
from collections.abc import Callable
from typing import Any

from camel.messages import BaseMessage
from camel.models import ModelFactory
from camel.toolkits import FunctionTool, RegisteredAgentToolkit
from camel.types import ModelPlatformType

from app.agent.listen_chat_agent import ListenChatAgent, logger
from app.model.chat import AgentModelConfig, Chat
from app.model.model_platform import (
    patch_azure_cloud_config,
    patch_bedrock_cloud_config,
)
from app.model.subscription_runtime import (
    apply_subscription_runtime,
    is_subscription_auth,
)
from app.component.environment import env
from app.service.task import ActionCreateAgentData, Agents, get_task_lock
from app.utils.event_loop_utils import _schedule_async_task


def _memory_window_size() -> int | None:
    """Sliding memory window (message count) for agents. DISABLED by default:
    CAMEL's window is a naive slice of the last N messages, which can cut
    BETWEEN an assistant `tool_calls` message and its `tool` result — the model
    API then 400s ("tool must follow tool_calls") and the whole task dies. So a
    message-COUNT window is unsafe whenever tools are used. Opt in only with
    UNDISCLOSED_AGENT_MEMORY_WINDOW if you understand that risk; the loop fix is
    handled by the recency directive + the on-demand soft-reset instead."""
    raw = env("UNDISCLOSED_AGENT_MEMORY_WINDOW", "0")
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _wants_thinking(options: Chat) -> bool:
    """True only when the user EXPLICITLY enabled thinking for this turn.

    Unlike the surfacing check in single_agent_service (which defaults on),
    requesting extended thinking costs real tokens, so here it must be an
    explicit opt-in (the frontend sends toolkit_config.thinking.enabled)."""
    cfg = (options.toolkit_config or {}).get("thinking")
    return isinstance(cfg, dict) and bool(cfg.get("enabled"))


def _thinking_budget() -> int:
    """Extended-thinking token budget for the legacy `enabled` API.
    Anthropic requires >= 1024."""
    raw = env("UNDISCLOSED_THINKING_BUDGET", "4096")
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = 4096
    return max(1024, value)


def _thinking_effort() -> str:
    """Effort level for the adaptive thinking API (Claude 5 / newer)."""
    val = (env("UNDISCLOSED_THINKING_EFFORT", "high") or "").strip().lower()
    return val if val in {"low", "medium", "high"} else "high"

# OpenAI chat-completions streaming only returns token usage when
# `stream_options.include_usage` is requested. Without it the request-level
# usage callback (on_request_usage) fires with 0 tokens, and because the
# step-level deactivate is zeroed once request-level reporting is active,
# streaming steps end up uncounted. These platforms use native (non-OpenAI)
# SDKs that reject `stream_options` and surface streaming usage on their own,
# so they are excluded from the injection below.
_NATIVE_STREAM_USAGE_PLATFORMS = {
    "anthropic",
    "aws-bedrock",
    "aws-bedrock-converse",
    "cohere",
    "mistral",
    "reka",
    "watsonx",
}

# Most recently built model backend (set in agent_model). Reused by lightweight
# side features like the git commit-message generator so they run on the same
# model the user is chatting with.
_LAST_MODEL: Any = None


def get_last_model() -> Any:
    """The model backend from the most recent agent build, or None if the user
    hasn't started a conversation yet this run."""
    return _LAST_MODEL


def agent_model(
    agent_name: str,
    system_message: str | BaseMessage,
    options: Chat,
    tools: list[FunctionTool | Callable] | None = None,
    prune_tool_calls_from_memory: bool = False,
    tool_names: list[str] | None = None,
    toolkits_to_register_agent: list[RegisteredAgentToolkit] | None = None,
    enable_snapshot_clean: bool = False,
    custom_model_config: AgentModelConfig | None = None,
):
    task_lock = get_task_lock(options.project_id)
    agent_id = str(uuid.uuid4())
    logger.info(
        f"Creating agent: {agent_name} with id: {agent_id} "
        f"for project: {options.project_id}"
    )
    # Use thread-safe scheduling to support parallel agent creation
    _schedule_async_task(
        task_lock.put_queue(
            ActionCreateAgentData(
                data={
                    "agent_name": agent_name,
                    "agent_id": agent_id,
                    "tools": tool_names or [],
                }
            )
        )
    )

    # Determine model configuration - use custom config if provided,
    # otherwise use task defaults
    config_attrs = ["model_platform", "model_type", "api_key", "api_url"]
    effective_config = {}

    if custom_model_config and custom_model_config.has_custom_config():
        for attr in config_attrs:
            custom_value = getattr(custom_model_config, attr, None)
            effective_config[attr] = (
                custom_value
                if custom_value is not None
                else getattr(options, attr)
            )
        extra_params = (
            custom_model_config.extra_params
            if custom_model_config.extra_params is not None
            else options.extra_params or {}
        )
        explicit_model_config = (
            custom_model_config.model_config_dict
            if custom_model_config.model_config_dict is not None
            else options.model_config_dict or {}
        )
        logger.info(
            f"Agent {agent_name} using custom model config: "
            f"platform={effective_config['model_platform']}, "
            f"type={effective_config['model_type']}"
        )
    else:
        for attr in config_attrs:
            effective_config[attr] = getattr(options, attr)
        extra_params = options.extra_params or {}
        explicit_model_config = options.model_config_dict or {}

    has_explicit_custom_api_key = (
        custom_model_config is not None
        and custom_model_config.has_custom_config()
        and custom_model_config.api_key is not None
    )
    use_subscription_runtime = (
        is_subscription_auth(options) and not has_explicit_custom_api_key
    )

    base_effective_config = dict(effective_config)
    base_extra_params = dict(extra_params or {})
    base_model_config = dict(explicit_model_config or {})

    def build_model(force_refresh: bool = False):
        effective_config = dict(base_effective_config)
        extra_params = dict(base_extra_params)
        explicit_model_config = dict(base_model_config)

        if use_subscription_runtime:
            effective_config, extra_params = apply_subscription_runtime(
                options,
                effective_config,
                extra_params,
                force_refresh=force_refresh,
            )

        effective_api_url = effective_config.get("api_url")
        is_effective_cloud = isinstance(effective_api_url, str) and any(
            marker in effective_api_url
            for marker in ("eigent-proxy", "proxy.undisclosed.ai")
        )

        # Cloud mode: inject default Bedrock region and adjust URL for proxy.
        if (
            effective_config.get("model_platform") == "aws-bedrock-converse"
            and is_effective_cloud
        ):
            (
                effective_config["api_url"],
                extra_params,
            ) = patch_bedrock_cloud_config(
                effective_config["api_url"], extra_params
            )
        # Cloud mode: default api_version for Azure-backed models so AzureOpenAI
        # construction does not blow up when the frontend omits extra_params.
        if (
            effective_config.get("model_platform") == "azure"
            and is_effective_cloud
        ):
            extra_params = patch_azure_cloud_config(extra_params)
        init_param_keys = {
            "api_version",
            "azure_ad_token",
            "azure_ad_token_provider",
            "max_retries",
            "timeout",
            "client",
            "async_client",
            "azure_deployment_name",
            "region_name",
            "aws_access_key_id",
            "aws_secret_access_key",
            "aws_session_token",
            "default_headers",
            "api_mode",
        }

        init_params = {}
        model_config: dict[str, Any] = {}

        # A nested model_config_dict may arrive inside legacy extra_params
        # while stored providers migrate to the explicit top-level field.
        # Treat it as less specific than the explicit request field.
        nested_model_config = extra_params.pop("model_config_dict", None)

        excluded_keys = {"model_platform", "model_type", "api_key", "url"}

        # Distribute extra_params between init_params and model_config
        for k, v in extra_params.items():
            if k in excluded_keys:
                continue
            # Skip empty values
            if v is None or (isinstance(v, str) and not v.strip()):
                continue

            if k in init_param_keys:
                init_params[k] = v
            else:
                model_config[k] = v

        if isinstance(nested_model_config, dict):
            model_config.update(nested_model_config)

        # The explicit model config is the canonical API and wins over legacy
        # flat values from extra_params.
        model_config.update(explicit_model_config)

        # Auto-inject prompt caching based on model platform
        try:
            model_platform_enum = ModelPlatformType(
                effective_config["model_platform"].lower()
            )
            if model_platform_enum in {
                ModelPlatformType.ANTHROPIC,
                ModelPlatformType.AWS_BEDROCK_CONVERSE,
            }:
                model_config.setdefault("cache_control", "5m")
            elif model_platform_enum == ModelPlatformType.OPENAI:
                model_config.setdefault(
                    "prompt_cache_key", str(options.project_id)
                )
        except (ValueError, AttributeError):
            logging.error(
                f"Invalid model platform: "
                f"{effective_config['model_platform']}",
                exc_info=True,
            )

        # Extended thinking: when the user turned "show thinking" on, actually
        # REQUEST reasoning from the model. Without this Claude emits no
        # reasoning_content, so the thinking block never streams anything.
        # Anthropic-only for now (its config accepts a `thinking` budget);
        # other providers are left untouched until their param is wired.
        if _wants_thinking(options):
            try:
                _mp = ModelPlatformType(
                    str(effective_config.get("model_platform", "")).lower()
                )
            except (ValueError, AttributeError):
                _mp = None
            # Strictly Anthropic platform only: the `thinking` key lives on
            # AnthropicConfig. Injecting it for an OpenAI-compatible gateway
            # (even one serving a claude-* model) would be rejected by that
            # provider's config and break the request.
            if _mp == ModelPlatformType.ANTHROPIC and "thinking" not in model_config:
                # Two Anthropic thinking APIs:
                #   - Claude 5 / newer: {"type": "adaptive"} + output_config.effort
                #   - older models:     {"type": "enabled", "budget_tokens": N}
                # Default to adaptive (sonnet-5 rejects "enabled"); override with
                # UNDISCLOSED_THINKING_TYPE=enabled for older Claude models.
                ttype = (
                    env("UNDISCLOSED_THINKING_TYPE", "adaptive") or ""
                ).strip().lower()
                if ttype == "enabled":
                    budget = _thinking_budget()
                    model_config["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": budget,
                    }
                    # max_tokens must exceed the thinking budget.
                    _mt = model_config.get("max_tokens")
                    if not isinstance(_mt, int) or _mt <= budget:
                        model_config["max_tokens"] = budget + 4096
                else:
                    model_config["thinking"] = {"type": "adaptive"}
                    model_config["output_config"] = {"effort": _thinking_effort()}
                logger.info(
                    "[thinking] requesting %s (output_config=%s) for %s",
                    model_config.get("thinking"),
                    model_config.get("output_config"),
                    effective_config.get("model_type"),
                )
                # Extended thinking (either form) requires temperature = 1 and no
                # top_p / top_k.
                model_config["temperature"] = 1.0
                model_config.pop("top_p", None)
                model_config.pop("top_k", None)

        # Runtime-owned values are applied after user configuration.
        if is_effective_cloud:
            model_config["user"] = str(options.project_id)
        if use_subscription_runtime:
            model_config["stream"] = True
            model_config["store"] = False
        if agent_name == Agents.task_agent:
            model_config["stream"] = True
        # The single agent is built with stream_accumulate=False (streaming
        # intent), but nothing enabled streaming — so responses arrived whole
        # and the live reasoning branch never ran (no "Thinking…" stream). Turn
        # streaming on so content AND reasoning deltas flow live.
        if agent_name == Agents.single_agent:
            model_config["stream"] = True
        if agent_name == Agents.browser_agent:
            try:
                model_platform_enum = ModelPlatformType(
                    effective_config["model_platform"].lower()
                )
                if model_platform_enum in {
                    ModelPlatformType.OPENAI,
                    ModelPlatformType.AZURE,
                    ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
                    ModelPlatformType.LITELLM,
                    ModelPlatformType.OPENROUTER,
                }:
                    model_config["parallel_tool_calls"] = False
            except (ValueError, AttributeError):
                logging.error(
                    f"Invalid model platform for browser agent: "
                    f"{effective_config['model_platform']}",
                    exc_info=True,
                )
                model_platform_enum = None

        if effective_config["model_platform"].lower() == "anthropic":
            if model_config.get("max_tokens") is None:
                model_config["max_tokens"] = 128000

        # Ensure streaming steps still report token usage. OpenAI-family
        # providers omit usage from streamed responses unless include_usage
        # is set, which would otherwise make request-level accounting count 0.
        # `stream_options: false` in extra_params opts out entirely, for
        # endpoints that reject the parameter (e.g. older vLLM/Azure).
        if model_config.get("stream_options") is False:
            model_config.pop("stream_options")
        elif model_config.get("stream") and (
            effective_config["model_platform"].lower()
            not in _NATIVE_STREAM_USAGE_PLATFORMS
        ):
            stream_options = model_config.setdefault("stream_options", {})
            if isinstance(stream_options, dict):
                stream_options.setdefault("include_usage", True)

        # Anthropic identity-linked keys: ensure the (separate) token counter
        # client also carries the workspace header, else its count_tokens
        # pre-flight call 400s before any chat request.
        from app.utils.anthropic_workspace import maybe_inject_token_counter

        maybe_inject_token_counter(
            effective_config["model_platform"],
            effective_config["model_type"],
            effective_config["api_key"],
            effective_config["api_url"],
            init_params,
            model_config,
        )
        return ModelFactory.create(
            model_platform=effective_config["model_platform"],
            model_type=effective_config["model_type"],
            api_key=effective_config["api_key"],
            url=effective_config["api_url"],
            model_config_dict=model_config or None,
            timeout=600,  # 10 minutes
            **init_params,
        )

    model = build_model()
    # Cache the most recent model so lightweight side features (e.g. the git
    # commit-message generator) can reuse the model the user is actually on,
    # without a separate chat request.
    global _LAST_MODEL
    _LAST_MODEL = model

    return ListenChatAgent(
        options.project_id,
        agent_name,
        system_message,
        model=model,
        tools=tools,
        agent_id=agent_id,
        message_window_size=_memory_window_size(),
        prune_tool_calls_from_memory=prune_tool_calls_from_memory,
        toolkits_to_register_agent=toolkits_to_register_agent,
        enable_snapshot_clean=enable_snapshot_clean,
        model_reload_callback=(
            (lambda: build_model(force_refresh=True))
            if use_subscription_runtime
            else None
        ),
        stream_accumulate=False,
    )
