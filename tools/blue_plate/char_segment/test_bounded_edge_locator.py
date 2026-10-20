"""Synthetic capacity/retirement tests, not development-image evaluation."""
from itertools import product
import json
from pathlib import Path

import cv2
import numpy as np

from bounded_edge_locator import PARAMETERS, bounded_rle, reference_components, close_edges, reference_gradients

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'tmp/blue-plate-char-segment/edge-localization-e0-preparation'


def check(mask, parameters):
    result = bounded_rle(mask, parameters)
    actual = sorted([dict(box=r['box'], area=r['area']) for r in result['components']], key=lambda r: (r['box'], r['area']))
    assert result['valid'] and actual == reference_components(mask)
    assert result['counters']['live_slots_at_end'] == 0
    for c in result['components']:
        # Independent 8-neighbour flood fill for statistics, without label IDs.
        y, x = divmod(c['uid'], mask.shape[1])
        stack, seen = [(x, y)], {(x, y)}
        while stack:
            a, b = stack.pop()
            for dx, dy in product((-1, 0, 1), repeat=2):
                xx, yy = a+dx, b+dy
                if 0 <= xx < mask.shape[1] and 0 <= yy < mask.shape[0] and mask[yy, xx] and (xx, yy) not in seen:
                    seen.add((xx, yy)); stack.append((xx, yy))
        assert c['area'] == len(seen)
        for key, expected in [('sum_x', sum(x for x, y in seen)), ('sum_y', sum(y for x, y in seen)),
                              ('sum_xx', sum(x*x for x, y in seen)), ('sum_xy', sum(x*y for x, y in seen)),
                              ('sum_yy', sum(y*y for x, y in seen))]:
            assert c[key] == expected, (key, c, expected)
    return result


def main():
    OUT.mkdir(exist_ok=True)
    dest = OUT / 'capacity-tests.json'
    if dest.exists():
        raise FileExistsError(dest)
    tiny = dict(PARAMETERS, min_width=1, max_width=1280, min_height=1, max_height=720,
                aspect_min_num=0, aspect_max_num=12800)
    for bits in range(512):
        mask = np.array([(bits >> j) & 1 for j in range(9)], dtype=bool).reshape(3, 3)
        check(mask, tiny)
    rng = np.random.default_rng(20261019)
    random_count = 0
    for _ in range(64):
        mask = rng.random((24, 32)) < 0.5
        # All components still traced; candidate filtering prevents unrelated
        # candidate-capacity failures in a partition-equivalence test.
        check(mask, PARAMETERS)
        random_count += 1
    diagonal = np.eye(30, dtype=bool)
    diag = check(diagonal, tiny)
    assert len(diag['components']) == 1
    late_bridge = np.zeros((8, 19), bool)
    late_bridge[:7, ::2] = True; late_bridge[7] = True
    bridge = check(late_bridge, tiny)
    assert len(bridge['components']) == 1 and bridge['counters']['union_merges'] == 9
    retire = np.zeros((100, 256), bool)
    retire[::2, ::2] = True
    reclaimed = check(retire, PARAMETERS)
    assert reclaimed['counters']['allocations'] == 6400 and reclaimed['counters']['peak_active_slots'] == 128
    slots = np.zeros((3, 768), bool)
    slots[0, :256:2] = True; slots[1, 512:768:2] = True
    peak = check(slots, PARAMETERS)
    assert peak['counters']['peak_active_slots'] == 256
    forced = bounded_rle(slots, dict(PARAMETERS, active_labels=255))
    assert not forced['valid'] and forced['overflow'][0]['kind'] == 'active_labels'
    too_many = np.zeros((2, 258), bool); too_many[0, ::2] = True
    run_over = bounded_rle(too_many)
    assert not run_over['valid'] and run_over['overflow'][0]['observed'] == 129
    boxes = np.zeros((72, 1280), bool)
    for i in range(33):
        y, x = (i//15)*24, (i % 15)*84
        boxes[y:y+20, x:x+80] = True
    candidate_over = bounded_rle(boxes)
    assert not candidate_over['valid'] and len(candidate_over['candidates']) == 32
    assert len(candidate_over['components']) == 33 and candidate_over['overflow'][0]['kind'] == 'candidates'
    morphology = 0
    for shape in [(7, 21), (24, 32), (47, 101)]:
        gx = rng.integers(-1020, 1021, shape, dtype=np.int16)
        edge, closed = close_edges(gx)
        golden = cv2.morphologyEx(edge.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 17), np.uint8),
                                borderType=cv2.BORDER_CONSTANT, borderValue=0)
        assert np.array_equal(closed, golden)
        morphology += 1
    report = dict(status='PASS_SYNTHETIC_ONLY', exhaustive_3x3_masks=512, random_partitions=random_count,
                  independent_checks=['OpenCV 8-connectivity bbox/area', 'scalar flood-fill moments', 'OpenCV close border=0'],
                  diagonal_component_count=1, late_bridge_union_merges=9, retired_and_reused_allocations=6400,
                  actual_256_slot_peak=peak['counters']['peak_active_slots'],
                  injected_255_slot_overflow=forced['overflow'], row_129_run_overflow=run_over['overflow'],
                  candidate_33_overflow=candidate_over['overflow'], candidate_storage_limit=32,
                  morphology_cases=morphology, image_reads=0, model_forwards=0,
                  gradient_reference_status='pending main exact RTL/small-sample review; no full development execution')
    dest.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
