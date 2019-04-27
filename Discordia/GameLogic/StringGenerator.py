import random
from typing import List


class TownNameGenerator:
    _prefixes: List[str] = [
        "New",
        "Old",
        "Lost"
    ]

    _roots: List[str] = [
        "Luxem",
        "Rodder",
        "Halls",
        "Alds",
        "Brax"
    ]

    _postfixes: List[str] = [
        "burg",
        "borough",
        "ton",
        "town",
        "ville",
        "brooke"
    ]

    @classmethod
    def generate_name(cls) -> str:
        name = ""
        if random.random() > 0.5:
            name += random.choice(cls._prefixes) + " "
        name += random.choice(cls._roots)
        name += random.choice(cls._postfixes)
        return name
