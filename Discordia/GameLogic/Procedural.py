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
    # Thresholds on tcod's Simplex noise (World._terrain_block), set so each terrain covers the share it
    # did on the old pnoise3 (water 18%, grass 29%, mountains 3%).
    water: float = 0.22
    grass: float = 0.59
    mountains: float = 0.79
    wilds: float = 0.1
    towns: float = 0.003
