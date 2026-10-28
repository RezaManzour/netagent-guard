"""One command: tests -> full evaluation -> plots -> README tables."""
import subprocess
import sys

from netagent_guard.eval import run
from netagent_guard.report import update_readme

if __name__ == "__main__":
    if "--skip-tests" not in sys.argv:
        subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], check=True)
    run("results", quick="--quick" in sys.argv)
    update_readme()
    print(open("results/tables.md").read())
