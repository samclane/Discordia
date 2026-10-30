"""
Simulation history: every command-line run of the game simulator (test_simulation) or the Discord server
simulator (test_server_simulation) appends one line to sim_history.jsonl: when, at which commit, with what
settings, and its headline numbers. Plotted over time, that shows whether the game is drifting as it's developed.

    python -m Discordia.test.sim_history [--html history.html]

prints what moved between the last two runs of each settings combination (a 500-tick run is only comparable to
another 500-tick run), and with --html draws every metric as its own chart against run number, one line per
settings combination, from history_template.html. The pytest smoke runs don't record.
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
    # Numbers from uncommitted code. The history itself doesn't count: the first of several runs dirties it.
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no", "--", ".", f":!{path.resolve().relative_to(REPO).as_posix()}"))
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


# Wall-clock numbers: they wobble run to run on the same code, so drift() leaves them out. A seeded run is
# otherwise deterministic, so any other metric that moves means the code changed what happens.
TIMINGS = ("run time (s)", "slowest order (s)")


def drift(runs: List[Dict]) -> str:
    """For each settings combination, what moved between its last two runs, in a line."""
    by_settings: Dict[tuple, List[Dict]] = {}
    for r in runs:
        by_settings.setdefault((r["kind"], json.dumps(r["params"], sort_keys=True)), []).append(r)
    lines = []
    for (kind, params), mine in by_settings.items():
        if len(mine) < 2:
            continue
        before, after = mine[-2], mine[-1]
        moved = [
            f"{metric} {before['metrics'][metric]} -> {value}"
            for metric, value in after["metrics"].items()
            if metric not in TIMINGS and metric in before["metrics"] and value != before["metrics"][metric]
        ]
        lines.append(f"{kind} {params}, {before['commit']} -> {after['commit']}: {'; '.join(moved) or 'no change'}")
    return "\n".join(lines) or "Fewer than two runs of any settings: nothing to compare."


def report(runs: List[Dict], path: Path):
    """Fill in history_template.html with every run, so the page stands alone."""
    blob = json.dumps(runs, separators=(",", ":")).replace("</", r"<\/")  # no early </script>
    path.write_text(TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", blob), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--history", default=str(HISTORY), help="the JSON lines file the simulators append to")
    parser.add_argument("--html", help="draw the dashboard here")
    args = parser.parse_args()
    runs = load(Path(args.history))
    print(drift(runs))
    if args.html:
        report(runs, Path(args.html))
        print(f"{len(runs)} runs drawn to {args.html}")
