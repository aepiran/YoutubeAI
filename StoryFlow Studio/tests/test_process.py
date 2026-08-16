from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from storyflow_studio.core import process


class ProcessHelperTests(unittest.TestCase):
    def test_third_party_popen_receives_no_window_flag(self) -> None:
        delegate = SimpleNamespace(Popen=mock.Mock(return_value="child"), PIPE=-1)
        owner = SimpleNamespace(subprocess=delegate)

        with mock.patch.object(process, "WINDOWS_NO_WINDOW", 0x08000000):
            process.hide_console_for_subprocess_owner(owner)
            result = owner.subprocess.Popen(["codex.exe"], creationflags=4)

        self.assertEqual(result, "child")
        delegate.Popen.assert_called_once_with(
            ["codex.exe"], creationflags=0x08000004
        )

    def test_wrapping_same_owner_twice_is_idempotent(self) -> None:
        delegate = SimpleNamespace(Popen=mock.Mock())
        owner = SimpleNamespace(subprocess=delegate)

        with mock.patch.object(process, "WINDOWS_NO_WINDOW", 0x08000000):
            process.hide_console_for_subprocess_owner(owner)
            wrapped = owner.subprocess
            process.hide_console_for_subprocess_owner(owner)

        self.assertIs(owner.subprocess, wrapped)


if __name__ == "__main__":
    unittest.main()
