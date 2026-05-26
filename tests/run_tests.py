"""Backward-compatible integration test suite runner wrapper."""
import subprocess
import sys

def main():
    print("=" * 60)
    print("RUNNING ALL ELT TESTS VIA PYTEST")
    print("=" * 60)
    
    # Execute pytest across the entire tests directory (both unit and integration suites)
    result = subprocess.run(["uv", "run", "pytest", "-v"])
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
