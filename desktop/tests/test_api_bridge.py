"""Tests for the pywebview JS bridge."""
from __future__ import annotations

from unittest.mock import MagicMock

import webview

from desktop.api_bridge import ApiBridge


def _bridge(window) -> ApiBridge:
    controller = MagicMock()
    controller.window = window
    return ApiBridge(controller)


def test_pick_folder_returns_first_selection():
    window = MagicMock()
    window.create_file_dialog.return_value = (r"C:\kernels",)
    assert _bridge(window).pick_folder() == r"C:\kernels"
    window.create_file_dialog.assert_called_once_with(webview.FOLDER_DIALOG)


def test_pick_folder_cancelled_returns_none():
    window = MagicMock()
    window.create_file_dialog.return_value = None
    assert _bridge(window).pick_folder() is None


def test_pick_folder_without_window_returns_none():
    assert _bridge(None).pick_folder() is None


def test_pick_folder_dialog_error_returns_none():
    window = MagicMock()
    window.create_file_dialog.side_effect = RuntimeError("no GUI")
    assert _bridge(window).pick_folder() is None
