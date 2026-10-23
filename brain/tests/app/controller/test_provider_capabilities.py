# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

import asyncio

from app.controller.chat_platform_controller import preview_provider_capabilities


def _preview(provider: str, model: str) -> dict:
    return asyncio.run(
        preview_provider_capabilities(provider_name=provider, model_type=model)
    )


def test_preview_tags_an_unsaved_vision_model():
    # The panel asks about a model before it is saved to providers.json.
    assert _preview("deepseek", "deepseek-v4-flash-vision-exp") == {
        "capabilities": ["vision", "thinking"]
    }


def test_preview_returns_no_tags_for_text_only_models():
    assert _preview("deepseek", "deepseek-chat") == {"capabilities": []}


def test_preview_tolerates_a_missing_model():
    assert _preview("deepseek", "") == {"capabilities": []}
