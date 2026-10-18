# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
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
# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========

"""Editor/agent scratch files.

The file toolkit writes a timestamped ``name.<ts>.bak`` copy before every
in-place edit, and editors leave ``.orig``/``.rej``/``.swp`` siblings behind.
These are never part of the project. Every listing, search and generated-file
scan skips them, and the repo's ``.gitignore`` keeps them out of git, so a
backup can exist without the agent having to clean it up.
"""

SCRATCH_FILE_SUFFIXES: tuple[str, ...] = (
    ".bak",
    ".orig",
    ".rej",
    ".backup",
    ".old",
    "~",
)


def is_scratch_file(name: str) -> bool:
    """True when ``name`` is an editor/agent scratch artifact."""
    return name.lower().endswith(SCRATCH_FILE_SUFFIXES)
