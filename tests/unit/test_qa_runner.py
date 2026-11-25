"""Exercise the QA runner's cross-thread portal in the current environment."""

import subprocess
import sys
from pathlib import Path


def test_qa_selector_supports_cross_thread_portal():
    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "import qa_pytest; qa_pytest.configure_selector(); "
        "import anyio.from_thread; "
        "p=anyio.from_thread.start_blocking_portal(); "
        "portal=p.__enter__(); print(portal.call(lambda: 42)); p.__exit__(None,None,None)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(root / "scripts")],
        capture_output=True,
        text=True,
        timeout=8,
        check=True,
    )
    assert result.stdout.strip() == "42"
