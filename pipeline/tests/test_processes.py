"""A real Windows child must have no console, while pipes keep working."""
import os
import subprocess
import sys

import pytest

from tsfm_live.processes import background_process_options


@pytest.mark.skipif(os.name != "nt", reason="Windows console behavior")
def test_windows_child_has_no_console_and_keeps_stdio_pipes():
    child = subprocess.run(
        [sys.executable, "-c", "import ctypes,sys; print(ctypes.windll.kernel32.GetConsoleWindow()); "
         "print(sys.stdin.read()); print('diagnostic',file=sys.stderr)"],
        input="request", text=True, capture_output=True, check=True,
        **background_process_options(),
    )
    assert child.stdout.splitlines() == ["0", "request"]
    assert child.stderr.strip() == "diagnostic"
