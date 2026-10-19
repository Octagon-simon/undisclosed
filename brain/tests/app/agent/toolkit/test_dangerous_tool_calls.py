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

"""Adversarial regression tests for dangerous tool calls.

`test_command_policy.py` covers the normal matrix. This file pins the
evasions: path-qualified binaries, wrapper prefixes, bundled shell flags,
and write targets that leave the workspace. Each case is a command a model
could plausibly emit to get around a naive substring check.
"""

from __future__ import annotations

import pytest

from app.agent.toolkit.command_policy import (
    _BLOCKED_BINARIES,
    _DESTRUCTIVE_BINARIES,
    CommandTier,
    assess_command,
    is_blocked,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "command",
    [
        "/bin/rm -rf build",
        "/usr/bin/sudo ls",
        "./rm old.txt",
        "env FOO=1 /bin/rm old.txt",
        "command rm old.txt",
        "nohup rm -rf build",
        "xargs rm",
        "printf x | xargs -0 rm",
        "echo $(sudo reboot)",
        "echo `rm -rf /`",
        "find . -exec rm {} +",
        "git -C repo rm tracked.txt",
        "eval 'rm -rf /'",
        "bash --command 'rm -rf /'",
        "powershell -c 'Remove-Item -Recurse build'",
        "cmd /c del /s /q build",
    ],
)
def test_wrapped_or_path_qualified_blocked_binaries(command: str) -> None:
    assert is_blocked(command)


@pytest.mark.parametrize(
    "command",
    [
        "bash -lc 'rm -rf /'",
        "bash -ic 'sudo reboot'",
        "bash -cl 'rm -rf /'",
        "sh -lc 'rm -rf /'",
        "zsh -lc 'rm -rf /'",
        "dash -lc 'rm -rf /'",
    ],
)
def test_bundled_shell_flags_do_not_hide_a_blocked_command(
    command: str,
) -> None:
    # `-lc` runs the string like `-c`; treating it as a script name would let
    # a blocked command through as a plain workspace write.
    assert is_blocked(command)


@pytest.mark.parametrize(
    "command",
    [
        "bash -lc 'git clean -fd'",
        "bash -lc 'git reset --hard HEAD~1'",
        "bash -lc 'git push origin main'",
    ],
)
def test_bundled_shell_flags_keep_destructive_commands_destructive(
    command: str,
) -> None:
    assert assess_command(command).tier == CommandTier.DESTRUCTIVE


@pytest.mark.parametrize(
    "command",
    [
        "chmod -R 777 /",
        "chown -R nobody /",
        "truncate -s 0 /etc/passwd",
        "mv notes.txt /etc/",
        "cp notes.txt /etc/",
        "cp -t /etc notes.txt",
        "install -m 777 app /usr/local/bin/app",
        "tee /etc/passwd",
        "zip /etc/backup.zip notes.txt",
        "echo x > /etc/passwd",
        "cat src.txt > ../outside.txt",
        "printf x >> /tmp/out.log",
        "echo x >/etc/passwd",
    ],
)
def test_writes_outside_the_workspace_need_approval_every_time(
    command: str, tmp_path
) -> None:
    # A workspace write would run silently in Auto. These resolve outside the
    # project, so they are destructive and prompt in every mode.
    assert assess_command(command, workspace=tmp_path).tier == (
        CommandTier.DESTRUCTIVE
    )


@pytest.mark.parametrize(
    "command",
    [
        "mkdir -p src/new",
        "touch notes.txt",
        "cp a.txt b.txt",
        "mv old.py new.py",
        "chmod +x run.sh",
        "truncate -s 0 out.log",
        "install -m 755 app bin/app",
        "tee build.log",
        "zip release.zip dist/app.js",
        "echo x > out.txt",
    ],
)
def test_writes_inside_the_workspace_stay_workspace_writes(
    command: str, tmp_path
) -> None:
    assert assess_command(command, workspace=tmp_path).tier == (
        CommandTier.WORKSPACE_WRITE
    )


@pytest.mark.parametrize(
    "command",
    ["ls > /dev/null", "ls > /dev/null 2>&1", "echo hi >/dev/null"],
)
def test_dev_null_redirects_stay_read_only(
    command: str, tmp_path
) -> None:
    assert assess_command(command, workspace=tmp_path).tier == (
        CommandTier.READ_ONLY
    )


@pytest.mark.parametrize("binary", sorted(_BLOCKED_BINARIES))
def test_every_blocked_binary_is_blocked(binary: str) -> None:
    # The public list and the classifier cannot drift without a red test.
    assert assess_command(f"{binary} --help").tier == CommandTier.BLOCKED


@pytest.mark.parametrize("binary", sorted(_DESTRUCTIVE_BINARIES))
def test_every_destructive_binary_prompts(binary: str) -> None:
    assert assess_command(f"{binary} --help").tier == (CommandTier.DESTRUCTIVE)
