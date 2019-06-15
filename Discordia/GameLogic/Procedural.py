import numpy as np


def normal(avg, positive=False, integer=False, spread=1.0):
    ans = np.random.normal(avg, scale=spread)

    if integer:
        ans = round(ans)
    if positive:
        ans = abs(ans)

    return ans