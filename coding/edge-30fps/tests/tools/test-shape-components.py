"""Compare row labels with an independent pixel flood fill, including diagonal joins."""
from collections import deque
import numpy as np
from shape_reference import row_components, DIRECTIONS

rng = np.random.default_rng(601010)
for case in range(500):
    edge = rng.random((int(rng.integers(1, 33)), int(rng.integers(1, 130)))) < rng.uniform(0, 1)
    remaining = {(int(x), int(y)) for y, x in np.argwhere(edge)}
    expected = []
    while remaining:
        seed = min(remaining, key=lambda p: (p[1], p[0]))
        remaining.remove(seed)
        queue, component = deque([seed]), {seed}
        while queue:
            x, y = queue.popleft()
            for dx, dy in DIRECTIONS:
                point = x+dx, y+dy
                if point in remaining:
                    remaining.remove(point)
                    component.add(point)
                    queue.append(point)
        expected.append((component, seed))
    assert row_components(edge) == expected, case
print('PASS 500 row-component maps against independent pixel flood fill')
