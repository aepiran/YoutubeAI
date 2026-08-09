from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock, patch

import main as app_main


class MainEntryTests(unittest.TestCase):
    def test_routes_packaged_stock_footage_app(self) -> None:
        stock_main = Mock(return_value=17)
        module = types.ModuleType("stock_footage_app")
        module.main = stock_main

        with (
            patch.dict(sys.modules, {"stock_footage_app": module}),
            patch.object(
                app_main.sys,
                "argv",
                ["FootageVideoBuilder.exe", "--stock-footage-app", "--project", "D:/p"],
            ),
        ):
            result = app_main.main()

        self.assertEqual(result, 17)
        stock_main.assert_called_once_with(["--project", "D:/p"])

    def test_routes_packaged_stock_worker_without_dropping_flag(self) -> None:
        stock_main = Mock(return_value=23)
        module = types.ModuleType("stock_footage_app")
        module.main = stock_main

        with (
            patch.dict(sys.modules, {"stock_footage_app": module}),
            patch.object(
                app_main.sys,
                "argv",
                ["FootageVideoBuilder.exe", "--stock-worker", "--csv", "plan.csv"],
            ),
        ):
            result = app_main.main()

        self.assertEqual(result, 23)
        stock_main.assert_called_once_with(["--stock-worker", "--csv", "plan.csv"])


if __name__ == "__main__":
    unittest.main()
