"""Synthetic E1 checks, with no development-image reads."""
import json
import numpy as np

from edge_local_refine import (detailed_structure, line_geometry, polarity_lines,
                               refine_candidate, merge_fragments)
from bounded_edge_locator import structure_evidence
from run_edge_localization import BASE, write_new
from run_edge_local_e1 import select


def main():
    out = BASE / 'edge-localization-e1-preparation'
    out.mkdir(exist_ok=True)
    dest = out / 'tests-final.json'
    if dest.exists():
        raise FileExistsError(dest)
    frame = np.zeros((180, 400, 3), np.uint8)
    for i, x in enumerate((65, 105, 150, 190, 230, 270, 310)):
        widths = [(0, 8), (10, 8)] if i == 0 else [(0, 18)]
        for dx, width in widths:
            frame[70:110, x+dx:x+dx+width] = 255
            frame[73:107, x+dx+2:x+dx+width-2] = 0
    coarse = dict(uid=-1, boundary_pass=True, expanded_box=[25, 30, 375, 150])
    cache = {}
    result = refine_candidate(frame, coarse, cache)
    assert 'coarse_-1' in cache and any(k.startswith('refined_') for k in cache)
    light = result['polarities'][0]
    assert light['status'] == 'lines_found', light
    assert len(light['lines']) == 1
    groups = light['lines'][0]['observed_groups']
    assert len(groups) == 7 and len(groups[0]['members']) == 2
    assert len(light['lines'][0]['source_component_uids']) == 8
    # Translation changes final coordinates, not fit tolerance or the chosen ink.
    original, reason = line_geometry(groups, coarse['expanded_box'])
    shifted, reason2 = line_geometry(groups, [45, 50, 395, 170])
    assert reason == reason2 == 'geometry_pass'
    assert np.array_equal(np.array(shifted['points_q16'])-original['points_q16'], np.full((4, 2), 20*65536))
    moved_groups = [dict(g, box=[g['box'][0], g['box'][1]+10, g['box'][2], g['box'][3]+10]) for g in groups]
    moved, why = line_geometry(moved_groups, coarse['expanded_box'])
    assert why == 'geometry_pass' and moved['slope_exact'] == original['slope_exact']
    assert np.array_equal(np.array(moved['points_q16'])-original['points_q16'], np.array([[0, 10*65536]]*4))
    # A six-glyph observation may not invent the missing first character.
    missing = frame.copy()
    missing[:, 65:83] = 0
    six = refine_candidate(missing, coarse)
    assert not six['polarities'][0]['lines']
    touching = [dict(g, box=g['box'].copy()) for g in groups]
    touching[0]['box'][0] = 0
    _, why = line_geometry(touching, coarse['expanded_box'])
    assert why == 'observed_ink_touches_search_boundary'
    assert not refine_candidate(frame, dict(coarse, boundary_pass=False))['polarities']
    # Fixed fragment capacity: 65 retained components fails without keeping top K.
    clutter = np.zeros((80, 240), np.uint8)
    for i in range(65):
        x, y = (i % 20)*10+1, (i//20)*10+1
        clutter[y:y+3, x:x+3] = 255
    capped = polarity_lines(clutter, 'light', [0, 0, 240, 80])
    assert capped['overflow'] and capped['status'] == 'fragment_capacity_overflow'
    # Trace instrumentation must preserve the exact frozen segment output.
    rng = np.random.default_rng(19)
    patterns = [np.zeros((64, 224, 3), np.uint8), rng.integers(0, 256, (64, 224, 3), dtype=np.uint8)]
    bars = patterns[0].copy()
    for x in (12, 45, 79, 110, 141, 172, 203):
        bars[12:52, x:x+10] = 255
    patterns.append(bars)
    for patch in patterns:
        before, after = structure_evidence(patch), detailed_structure(patch)
        for a, b in zip(before, after):
            for key in ('valid', 'segmentation_pass', 'rects', 'mask_sha256'):
                assert a[key] == b[key]
    assert detailed_structure(patterns[0])[0]['failure']['reason'] == 'global_otsu_single_bin'
    dummy = dict(uid=0, overflow=False, refinements=[dict(points_q16=[[0, 0]]*4, valid=True)])
    assert select([dummy])['status'] == 'selected'
    assert select([dummy, dict(dummy, uid=1)])['status'] == 'selected'
    different = dict(uid=1, overflow=False, refinements=[dict(points_q16=[[1, 1]]*4, valid=True)])
    assert select([dummy, different])['status'] == 'ambiguity'
    excess = dict(uid=2, overflow=False, refinements=[dict(points_q16=[[i, i]]*4, valid=True) for i in range(33)])
    capped_frame = select([excess])
    assert capped_frame['status'] == 'overflow' and capped_frame['stored_geometry_count'] == 32
    assert capped_frame['selected_index'] is None
    json.dumps(result)
    write_new(dest, dict(status='PASS', synthetic_refinement_calls=2,
              checks=['two-fragment first glyph observed', 'missing first glyph rejected',
                      'vertical and global translation invariance', 'observed search-boundary contact rejected',
                      'frozen coarse boundary rejected', '65 fragments overflow', 'exact structure tracing', 'serialization',
                      'cache consistency', 'exact duplicate dedup', 'distinct lines ambiguity', '33 frame hypotheses overflow'],
              local_lines=len(light['lines']), refinements=len(result['refinements']),
              refined_valid=sum(r['valid'] for r in result['refinements']),
              dataset_image_reads=0, model_forwards=0))
    print('PASS synthetic local refinement and structure tracing')


if __name__ == '__main__':
    main()
