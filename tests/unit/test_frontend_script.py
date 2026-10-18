"""Optional Node built-in checks; no npm modules or browser accuracy claim."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_dashboard_script_contract_and_unsafe_values():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for optional dashboard script checks")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([node, "--test", "tests/frontend/evidence.test.cjs"], cwd=root,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
