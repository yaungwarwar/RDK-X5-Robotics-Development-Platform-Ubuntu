import shutil
import subprocess
from pathlib import Path


def test_node_qa_process_guard_regressions():
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [shutil.which("node"), "--test", "tests/unit/test_qa_guard.mjs"],
        cwd=root,
        check=True,
        timeout=20,
    )
