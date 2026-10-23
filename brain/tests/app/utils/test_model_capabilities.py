# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from app.utils.model_capabilities import (
    model_capability_tags,
    model_supports_thinking,
    model_supports_vision,
)


def test_vision_accepts_configured_vision_model():
    assert model_supports_vision("deepseek", "deepseek-v4-flash-vision-exp")
    assert model_supports_vision("openai", "gpt-4o")
    assert model_supports_vision("anthropic", "claude-sonnet-4-5")
    assert model_supports_vision("ollama", "qwen2.5-vl:7b")
    assert model_supports_vision("ollama", "llava:13b")


def test_vision_rejects_text_only_models():
    assert not model_supports_vision("deepseek", "deepseek-v4-flash")
    assert not model_supports_vision("openai", "gpt-3.5-turbo")
    assert not model_supports_vision(None, None)
    assert not model_supports_vision("", "")


def test_thinking_covers_wired_providers():
    # Anthropic: the request side is wired in agent_model.
    assert model_supports_thinking("anthropic", "claude-sonnet-4-5")
    assert model_supports_thinking("anthropic", "claude-opus-4-1")
    # DeepSeek reasoning models return reasoning_content without a param.
    assert model_supports_thinking("deepseek", "deepseek-reasoner")
    assert model_supports_thinking("deepseek", "deepseek-v4-flash")


def test_thinking_excludes_models_this_app_cannot_get_reasoning_from():
    assert not model_supports_thinking("deepseek", "deepseek-chat")
    # OpenAI reasoning models need reasoning_effort, which is not wired yet.
    assert not model_supports_thinking("openai", "o3")
    # Claude 3.5 predates extended thinking.
    assert not model_supports_thinking("anthropic", "claude-3-5-sonnet")


def test_tags_are_ordered_and_complete():
    assert model_capability_tags("deepseek", "deepseek-v4-flash-vision-exp") == [
        "vision",
        "thinking",
    ]
    assert model_capability_tags("openai", "gpt-4o") == ["vision"]
    assert model_capability_tags("deepseek", "deepseek-chat") == []
    assert model_capability_tags(None, None) == []
