import subprocess
import sys


def test_cli_imports_and_shows_help():
    result = subprocess.run([sys.executable, "-m", "tracking_la.cli", "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "outcomes" in result.stdout
