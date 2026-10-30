"""
The numbers behind the game live in data/*.json, not in code. This is the one place that reads them.

Every data file is a top-level object keyed by the thing it defines -- a class name, a name-list name --
and every loader here fails at import if a file is broken, rather than mid-game.
"""

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from Discordia import DATA_FOLDER

__all__ = ["DATA_FOLDER", "load", "FromData", "stocked"]


def load(
    path: Path, enums: Optional[Dict[str, type]] = None
) -> Dict[str, Dict[str, Any]]:
    """Blocks keyed by name. Fields named in `enums` are written by name in the JSON, so the file stays readable."""
    enums = enums or {}
    return {
        key: {
            field: getattr(enums[field], value) if field in enums else value
            for field, value in block.items()
        }
        for key, block in json.loads(path.read_text(encoding="utf-8")).items()
    }


class FromData:
    """
    Mixin for gear whose whole definition is its stat block.

    Subclass it once per data file with STATS set to that file's blocks, then list that subclass first in
    the bases of each piece of gear -- its __init__ has to win the MRO to supply the stats.
    """

    STATS: Dict[str, Dict[str, Any]] = {}

    def __init__(self):
        stats = self.STATS[type(self).__name__]
        super().__init__(**{field: value for field, value in stats.items() if field != "store"})


def _descendants(cls: type) -> Iterator[type]:
    for sub in cls.__subclasses__():
        yield sub
        yield from _descendants(sub)


def stocked() -> List[type]:
    """Every piece of gear with a stat block that a store may sell: all of them but blocks saying "store": false
    (fists, salvage). In the order the classes are defined, which a world's seeded stores depend on."""
    found: List[type] = []
    for cls in _descendants(FromData):
        block = cls.STATS.get(cls.__name__)
        if block is not None and block.get("store", True) and cls not in found:
            found.append(cls)
    return found
