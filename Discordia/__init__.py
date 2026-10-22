from pathlib import Path

SPRITE_FOLDER = Path("./Discordia/Interface/Rendering/Sprites")

# Anchored on the package, not the working directory: game data is loaded wherever the server runs from.
DATA_FOLDER = Path(__file__).parent / "data"


_ADJECTIVES = "Elegant Grim Rusty Brave Sly Quiet Feral Lucky Gilded Hollow Wary Bold Dusty Swift Stout Pale".split()
_VERBS = "Starting Raiding Looting Wandering Lurking Hunting Scouting Haggling Digging Marching Sneaking Brawling Fleeing Camping Trading Roaming".split()
_ANIMALS = "Rabbit Badger Crow Wolf Boar Ferret Heron Lynx Mole Newt Otter Rat Stag Toad Viper Weasel".split()


def nice_name(hex_id: str) -> str:
    """A readable name for a hex id (commit hash, uuid.hex), e.g. "ElegantStartingRabbit". Same id, same name."""
    # ponytail: 12 bits of name, so ids collide 1 in 4096; it's for show, keep the id next to it.
    n = int(hex_id, 16)
    words = []
    for word_list in (_ADJECTIVES, _VERBS, _ANIMALS):
        n, i = divmod(n, len(word_list))
        words.append(word_list[i])
    return "".join(words)


def _version() -> str:
    """The checked-out commit, e.g. "GrimLootingOtter (58c75b9, 2026-10-18)": deploys are a git pull, so that's what's running."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%h %cs"], cwd=Path(__file__).parent, capture_output=True, text=True, timeout=5
        )
        commit, date = out.stdout.split()
        return f"{nice_name(commit)} ({commit}, {date})"
    except (OSError, subprocess.SubprocessError, ValueError):
        return "unknown"


# ponytail: read once at import, so a pull without a restart still shows the version that's running.
VERSION = _version()
