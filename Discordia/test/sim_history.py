"""
Simulation history: every command-line run of the game simulator (test_simulation) or the Discord server
simulator (test_server_simulation) appends one line to sim_history.jsonl: when, at which commit, with what
settings, and its headline numbers. Plotted over time, that shows whether the game is drifting as it's developed.

    python -m Discordia.test.sim_history --html history.html

draws every metric as its own chart against run number, one line per settings combination (a 500-tick run is
only comparable to another 500-tick run), from history_template.html. The pytest smoke runs don't record.
"""

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

HISTORY = Path(__file__).with_name("sim_history.jsonl")
TEMPLATE = Path(__file__).with_name("history_template.html")
REPO = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def record(kind: str, params: Dict, metrics: Dict[str, float], path: Path = HISTORY) -> Dict:
    """Append one run. `kind` is "game" or "server"; `params` are the settings that make runs comparable."""
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))  # numbers from uncommitted code
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": (_git("rev-parse", "--short", "HEAD") or "unknown") + ("+dirty" if dirty else ""),
        "subject": _git("log", "-1", "--format=%s"),
        "kind": kind,
        "params": params,
        "metrics": metrics,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def load(path: Path = HISTORY) -> List[Dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def report(runs: List[Dict], path: Path):
    """Fill in history_template.html with every run, so the page stands alone."""
    blob = json.dumps(runs, separators=(",", ":")).replace("</", r"<\/")  # no early </script>
    path.write_text(TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", blob), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--history", default=str(HISTORY), help="the JSON lines file the simulators append to")
    parser.add_argument("--html", default="history.html", help="draw the dashboard here")
    args = parser.parse_args()
    runs = load(Path(args.history))
    report(runs, Path(args.html))
    print(f"{len(runs)} runs drawn to {args.html}")
