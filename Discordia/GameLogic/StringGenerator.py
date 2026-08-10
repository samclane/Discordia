"""Name generation. The word lists live in data/names.json, so adding names needs no code change."""

import json
import random
from pathlib import Path
from typing import Dict, List

from Discordia import DATA_FOLDER

NAMES_PATH = DATA_FOLDER / "names.json"


class NameGenerator:
    """Builds "[prefix ]root+postfix" out of one named set of word lists."""

    def __init__(self, prefixes: List[str], roots: List[str], postfixes: List[str]):
        self.prefixes = prefixes
        self.roots = roots
        self.postfixes = postfixes

    def generate_name(self) -> str:
        name = ""
        if self.prefixes and random.random() > 0.5:
            name += random.choice(self.prefixes) + " "
        name += random.choice(self.roots)
        name += random.choice(self.postfixes)
        return name


def load(path: Path = NAMES_PATH) -> Dict[str, NameGenerator]:
    """One generator per top-level key. A missing or misspelled list raises here, at import, not mid-game."""
    return {
        key: NameGenerator(**word_lists)
        for key, word_lists in json.loads(path.read_text(encoding="utf-8")).items()
    }


GENERATORS = load()

TownNameGenerator = GENERATORS["town"]
WildsNameGenerator = GENERATORS["wilds"]
MaleNameGenerator = GENERATORS["character_male"]
FemaleNameGenerator = GENERATORS["character_female"]
