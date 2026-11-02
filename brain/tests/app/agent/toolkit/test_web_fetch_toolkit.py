# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from types import SimpleNamespace

import camel.toolkits.web_fetch_toolkit as camel_web_fetch
import pytest
from camel.models import StubModel
from camel.types import ModelType
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta

from app.agent.toolkit.web_fetch_toolkit import WebFetchToolkit

PAGE_HTML = "<html><body><h1>Hi</h1><p>Page body.</p></body></html>"


def _chunk(content="", finish_reason=None, usage=None, with_choices=True):
    return ChatCompletionChunk(
        id="fake",
        model="stub",
        object="chat.completion.chunk",
        created=0,
        choices=(
            [
                Choice(
                    index=0,
                    delta=ChoiceDelta(content=content),
                    finish_reason=finish_reason,
                )
            ]
            if with_choices
            else []
        ),
        usage=usage,
    )


class _Stream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __iter__(self):
        return iter(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StreamingStubModel(StubModel):
    """Stub backend that streams deltas, like every brain model does."""

    def __init__(self):
        super().__init__(ModelType.STUB, {"stream": True})

    def _run(self, messages, response_format=None, tools=None):
        return _Stream(
            [
                _chunk("Hello "),
                _chunk("from the page."),
                _chunk(finish_reason="stop"),
                _chunk(
                    usage=CompletionUsage(
                        prompt_tokens=5, completion_tokens=5, total_tokens=10
                    ),
                    with_choices=False,
                ),
            ]
        )


class _FakeResponse:
    is_error = False
    headers = {"content-type": "text/html"}

    def __init__(self, text):
        self.text = text


class _FakeClient:
    def __init__(self, text):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        return _FakeResponse(self._text)


@pytest.fixture
def page(monkeypatch):
    """Serve PAGE_HTML to the toolkit without touching the network."""

    def _install(text):
        monkeypatch.setattr(
            camel_web_fetch,
            "httpx",
            SimpleNamespace(
                Client=lambda **kwargs: _FakeClient(text), HTTPError=Exception
            ),
        )

    _install(PAGE_HTML)
    return _install


@pytest.fixture
def toolkit():
    toolkit = WebFetchToolkit()
    toolkit._agent = SimpleNamespace(
        model_backend=_StreamingStubModel(), output_language=None
    )
    return toolkit


@pytest.mark.unit
def test_streamed_summary_text_is_returned(toolkit, page):
    result = toolkit.web_fetch_and_analyze("https://example.com", "say hi")

    assert result == "Hello from the page."


@pytest.mark.unit
def test_summary_agent_accumulates_streamed_deltas(toolkit):
    agent = toolkit._get_summary_agent()

    assert agent is not None
    assert agent.stream_accumulate is True


@pytest.mark.unit
def test_blank_summary_returns_actionable_error(monkeypatch, toolkit, page):
    class _BlankAgent:
        def step(self, _message):
            return SimpleNamespace(msgs=[SimpleNamespace(content="")])

    monkeypatch.setattr(
        WebFetchToolkit, "_get_summary_agent", lambda self: _BlankAgent()
    )

    result = toolkit.web_fetch_and_analyze("https://example.com", "say hi")

    assert result.startswith("Error: fetched https://example.com")
    assert "max_chars" in result
