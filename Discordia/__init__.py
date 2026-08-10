from pathlib import Path

SPRITE_FOLDER = Path("./Discordia/Interface/Rendering/Sprites")

# Anchored on the package, not the working directory: game data is loaded wherever the server runs from.
DATA_FOLDER = Path(__file__).parent / "data"
