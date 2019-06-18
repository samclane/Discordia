from dataclasses import dataclass

import numpy as np


def normal(avg, positive=False, integer=False, spread=1.0):
    ans = np.random.normal(avg, scale=spread)

    if integer:
        ans = round(ans)
    if positive:
        ans = abs(ans)

    return ans


@dataclass
class WorldGenerationParameters:
    resolution_constant: float = 0.2
    water: float = .075
    grass: float = .3
    mountains: float = .65
    wilds: float = .1
    towns: float = .003
