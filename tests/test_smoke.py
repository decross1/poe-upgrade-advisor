import subprocess
import sys


def test_repository_invariants_smoke() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_invariants.py"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
