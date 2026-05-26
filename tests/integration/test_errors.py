import subprocess

def test_missing_job():
    """TEST 13: Job not found error"""
    result = subprocess.run(
        ["uv", "run", "elt", "run", "--job", "nonexistent_job"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode != 0, f"Expected non-zero exit code for nonexistent job, got {result.returncode}"
    output = result.stdout + result.stderr
    assert "not found" in output.lower(), f"Expected 'not found' in error message, got: {output}"


def test_validate_command():
    """TEST 10: Validate command"""
    result = subprocess.run(
        ["uv", "run", "elt", "validate"],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"Expected validation to succeed, got exit code {result.returncode}"
    output = result.stdout + result.stderr
    assert "OK" in output, f"Expected 'OK' in validation logs, got: {output}"
