"""Run the page's copyable commands, not a separately maintained example."""
from html.parser import HTMLParser
from pathlib import Path
import shlex
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from app import store
from app.main import app


class _CommandSnippet(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_commands = False
        self.in_pre = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "div" and dict(attrs).get("aria-label") == "flip the break button":
            self.in_commands = True
        if self.in_commands and tag == "pre":
            self.in_pre = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.in_pre = False
        if tag == "div":
            self.in_commands = False

    def handle_data(self, data):
        if self.in_pre:
            self.parts.append(data)


@pytest.fixture
def local_service():
    """Use an allocated loopback socket; never depend on a user's running app."""
    store.set_fault("none")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "local demo server did not start"
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        worker.join(timeout=5)
        sock.close()
        store.set_fault("none")
        assert not worker.is_alive(), "local demo server did not stop"


def test_displayed_curl_commands_switch_to_failure_then_recover(local_service):
    parser = _CommandSnippet()
    parser.feed((Path(__file__).parents[1] / "dashboard/index.html").read_text())
    snippet = "".join(parser.parts).replace("\\\n", "")
    statuses = []
    bodies = []
    for line in snippet.splitlines():
        command = shlex.split(line, comments=True)
        if not command:
            continue
        assert command[0] == "curl", "demo snippet must contain curl commands only"
        command = [arg.replace("localhost:8799", local_service) for arg in command]
        command += ["--silent", "--show-error", "--max-time", "5", "--noproxy", "*",
                    "--write-out", "\n%{http_code}"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=7)
        assert result.returncode == 0, result.stderr
        body, status = result.stdout.rsplit("\n", 1)
        statuses.append(int(status))
        bodies.append(body)

    assert statuses == [200, 500, 200, 200]
    assert bodies[0] == '{"mode":"error"}'
    assert bodies[1] == '{"detail":"order lookup failed"}'
    assert bodies[2] == '{"mode":"none"}'
    assert '"tracking":"TRK0001"' in bodies[3]
