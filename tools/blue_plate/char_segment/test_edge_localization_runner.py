"""Synthetic runner checks; no dataset images or model weights are opened."""
import json

import numpy as np

from run_edge_localization import (BASE, canvas, ground_truth, candidate_metrics,
                                   oracle_foreground, summarize, write_new)
from bounded_edge_locator import locate_from_gx, structure_evidence


def main():
    dest = BASE / 'edge-localization-e0-preparation/runner-tests.json'
    if dest.exists():
        raise FileExistsError(dest)
    image = np.zeros((60, 80, 3), np.uint8)
    image[:, :] = [10, 20, 30]
    frame, transform = canvas(image)
    assert transform == dict(source_wh=[80, 60], resized_wh=[960, 720], offset_xy=[160, 0])
    assert np.all(frame[:, :160] == 0) and np.all(frame[:, 160:1120] == [10, 20, 30])
    sample = dict(points=[[55, 35], [25, 35], [25, 25], [55, 25]])
    points, domain = ground_truth(sample, transform)
    assert domain['in_predeclared_geometry_domain']
    assert np.array_equal(points, [[460, 300], [820, 300], [820, 420], [460, 420]])
    zones = {'light': [[np.array([470., 800.]), np.array([310., 410.])] for _ in range(7)]}
    full = candidate_metrics(dict(expanded_box=[460, 300, 821, 421]), points, zones)
    assert full['iou'] == 1 and full['gt_full_containment'] and max(full['corner_errors_px']) == 0
    assert not full['foreground_clipping_diagnostic'][0]['any_zone_over_15_percent']
    cut = candidate_metrics(dict(expanded_box=[460, 300, 641, 421]), points, zones)
    assert abs(cut['iou']-.5) < 1e-6 and not cut['gt_full_containment']
    assert cut['foreground_clipping_diagnostic'][0]['any_zone_over_15_percent']
    assert cut['character_clipping_confirmed'] is None
    # Seven bars satisfy the structure rule but are not proof of readable glyphs.
    patch = np.zeros((64, 224, 3), np.uint8)
    for x in (12, 45, 79, 110, 141, 172, 203):
        patch[12:52, x:x+10] = 255
    structure = structure_evidence(patch)
    assert structure[0]['valid']
    oracle, polar_zones = oracle_foreground(patch, np.array([[0, 0], [223, 0], [223, 63], [0, 63]]))
    assert 'light' in polar_zones and len(polar_zones['light']) == 7
    assert oracle['confirmed_character_visibility'] is None
    frame = np.zeros((96, 256, 3), np.uint8)
    empty = locate_from_gx(frame, np.zeros((96, 256), np.int16))
    assert empty['status'] == 'no_structural_candidate' and empty['completed_components_match_opencv']
    gx = np.zeros((96, 256), np.int16)
    gx[30:60, 60:160] = 100
    solid = locate_from_gx(frame, gx)
    assert len(solid['candidates']) == 1 and solid['status'] == 'no_structural_candidate'
    assert len(solid['candidates'][0]['polarities']) == 2
    # Exercise exact serialization and summary construction before the data run.
    row = dict(sample_index=-1, domain=domain, old_no_color_outcome='correct', entries={'A': empty, 'B': empty})
    summary = summarize([row])
    assert summary['old251_correct']['A']['localization_loss_iou50_ids'] == [-1]
    json.dumps(dict(empty=empty, solid=solid, structure=structure, oracle=oracle, summary=summary))
    write_new(dest, dict(status='PASS_SYNTHETIC_ONLY', tests=['canvas', 'GT evaluation isolation',
              'exact and clipped polygon', 'foreground clipping diagnostic', 'seven-bars counterexample',
              'empty locator', 'single-component dual polarity', 'JSON serialization', 'summary'],
              source_image_reads=0, dataset_locator_calls=0, synthetic_locator_calls=2, model_forwards=0))
    print('PASS synthetic runner checks; 0 source images / 0 model forwards')


if __name__ == '__main__':
    main()
