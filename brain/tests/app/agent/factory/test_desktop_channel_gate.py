# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from types import SimpleNamespace

import pytest

from app.agent.factory import toolkit_assembler as assembler

pytestmark = pytest.mark.unit


def _options(channel=None, desktop=None):
    options = SimpleNamespace(channel=channel, toolkit_config=None)
    if desktop is not None:
        options.toolkit_config = {"desktop": desktop}
    return options


def _config(desktop=None):
    config = dict(assembler.DEFAULT_SINGLE_AGENT_TOOLKIT_CONFIG)
    if desktop is not None:
        config["desktop"] = desktop
    return config


def test_desktop_allowed_for_a_desktop_turn():
    assert assembler._desktop_channel_allowed(_config(), _options("desktop"))


def test_desktop_allowed_when_the_channel_is_unset():
    assert assembler._desktop_channel_allowed(
        _config(), SimpleNamespace(toolkit_config=None)
    )


@pytest.mark.parametrize(
    "channel", ["slack", "whatsapp", "telegram", "remote_control"]
)
def test_desktop_withheld_for_remote_channels(channel):
    assert not assembler._desktop_channel_allowed(
        _config(), _options(channel)
    )


def test_desktop_allowed_for_the_embedded_editor_panel():
    """The editor mounts the panel as a web bundle; that is still this Mac."""
    assert assembler._desktop_channel_allowed(_config(), _options("web"))


def test_channel_list_can_be_widened_by_config():
    config = _config({"enabled": True, "channels": ["desktop", "CLI"]})
    assert assembler._desktop_channel_allowed(config, _options("cli"))


def test_channel_list_can_be_narrowed_to_nothing():
    config = _config({"enabled": True, "channels": []})
    assert not assembler._desktop_channel_allowed(config, _options("desktop"))


@pytest.mark.asyncio
async def test_router_stamps_the_inbound_channel_on_the_chat(monkeypatch):
    """A Slack turn must build a Chat that says so, or the gate never fires."""
    from app.controller import chat_controller
    from app.router_layer import message_router as router_mod
    from app.router_layer.interface import InboundMessage

    captured = {}

    async def fake_stream(chat, request):
        captured["chat"] = chat

        async def empty():
            for _ in ():
                yield None

        return empty()

    monkeypatch.setattr(chat_controller, "start_chat_stream", fake_stream)
    message = InboundMessage(
        session_id="sess",
        channel="slack",
        user_id="U123",
        payload={"content": "hi", "project_id": "proj"},
        headers={},
    )

    async for _ in router_mod.DefaultMessageRouter()._route_chat(
        message, request=SimpleNamespace()
    ):
        pass

    assert captured["chat"].channel == "slack"
    assert not assembler._desktop_channel_allowed(
        _config(), captured["chat"]
    )
