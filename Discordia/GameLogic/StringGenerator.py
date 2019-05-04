import random
from abc import ABC
from typing import List


class NameGenerator(ABC):
    _prefixes: List[str]
    _roots: List[str]
    _postfixes: List[str]

    @classmethod
    def generate_name(cls) -> str:
        name = ""
        if random.random() > 0.5:
            name += random.choice(cls._prefixes) + " "
        name += random.choice(cls._roots)
        name += random.choice(cls._postfixes)
        return name


class TownNameGenerator(NameGenerator):
    _prefixes = [
        "New",
        "Old",
        "Lost"
    ]

    _roots = [
        "Luxem",
        "Rodder",
        "Halls",
        "Alds",
        "Brax"
    ]

    _postfixes = [
        "burg",
        "borough",
        "ton",
        "town",
        "ville",
        "brooke"
    ]


class WildsNameGenerator(NameGenerator):
    _prefixes = [
        "The",
        "A",
    ]

    _roots = [
        "Dark ",
        "Foreboding ",
        "Evil ",
    ]

    _postfixes = [
        "Forrest",
        "Swamp",
        "Bog",
        "Fen",
        "Marsh"
    ]

