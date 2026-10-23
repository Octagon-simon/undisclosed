# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

import pytest

from app.agent.factory.single_agent import resolve_capability_name

AVAILABLE = [
    "Image Reader",
    "Page Screenshots",
    "Browser Toolkit",
    "Test Runner",
]


@pytest.mark.unit
def test_exact_and_case_insensitive_match():
    assert resolve_capability_name("Image Reader", AVAILABLE) == "Image Reader"
    assert (
        resolve_capability_name("page screenshots", AVAILABLE)
        == "Page Screenshots"
    )


@pytest.mark.unit
def test_model_may_echo_the_purpose_hint():
    label = "Page Screenshots: capture a live web page URL"
    assert resolve_capability_name(label, AVAILABLE) == "Page Screenshots"


@pytest.mark.unit
def test_legacy_and_singular_labels_still_resolve():
    assert (
        resolve_capability_name("Screenshot Toolkit", AVAILABLE) == "Image Reader"
    )
    assert (
        resolve_capability_name("Page Screenshot", AVAILABLE)
        == "Page Screenshots"
    )


@pytest.mark.unit
def test_copied_list_bullet_still_resolves():
    label = "- Image Reader: read an image file on disk"
    assert resolve_capability_name(label, AVAILABLE) == "Image Reader"


@pytest.mark.unit
def test_unique_substring_match():
    assert (
        resolve_capability_name("browser", AVAILABLE) == "Browser Toolkit"
    )


@pytest.mark.unit
def test_unknown_name_is_not_guessed():
    assert resolve_capability_name("Slack Toolkit", AVAILABLE) is None
    assert resolve_capability_name("", AVAILABLE) is None
