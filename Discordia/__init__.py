from pathlib import Path

SPRITE_FOLDER = Path("./Discordia/Interface/Rendering/Sprites")

# Anchored on the package, not the working directory: game data is loaded wherever the server runs from.
DATA_FOLDER = Path(__file__).parent / "data"


def _version() -> str:
    """The checked-out commit, e.g. "58c75b9 (2026-10-18)": deploys are a git pull, so that's what's running."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%h (%cs)"], cwd=Path(__file__).parent, capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# ponytail: read once at import, so a pull without a restart still shows the version that's running.
VERSION = _version()
