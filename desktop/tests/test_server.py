"""Tests for desktop server helpers (pure parts only)."""
from __future__ import annotations

import socket

from desktop import server


def test_port_in_use_false_for_free_port():
    # bind a socket to grab a free port, then release it
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    assert server.port_in_use(free_port) is False


def test_port_in_use_true_when_listening():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        assert server.port_in_use(port) is True


def test_wait_for_server_times_out_fast():
    # nothing is listening on this URL; should return False within the timeout
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert server.wait_for_server(f"http://127.0.0.1:{port}/api/status", timeout=1.0) is False
