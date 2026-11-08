"""run_data.py: run the whole data pipeline in order. Stops at the first failure.

    python run_data.py

Steps: fetch (download, skipped if already frozen) -> panel (clean + samples) -> validate -> explore
-> data_report (codebook + data section). Extra options are passed to every step, e.g.
    python run_data.py --config config/settings.yaml
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = ["fetch", "panel", "validate", "explore", "data_report"]
NO_CONFIG = {"explore"}          # explore.py has its own options


def main():
    extra = sys.argv[1:]
    for step in STEPS:
        print(f"\n===== {step} =====", flush=True)
        args = [] if step in NO_CONFIG else extra
        r = subprocess.run([sys.executable, str(HERE / "src" / f"{step}.py"), *args], cwd=HERE)
        if r.returncode != 0:
            sys.exit(f"\nStopped: step '{step}' failed. Fix it, then run this file again "
                     f"(steps already frozen are skipped).")
    print("\nAll steps finished. Outputs: results/, data/processed/, report/data_section.md, CODEBOOK.md")


if __name__ == "__main__":
    main()
