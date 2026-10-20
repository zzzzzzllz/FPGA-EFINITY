"""One frozen local refinement per valid E0 A candidate, no full-frame locator."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import cv2
import numpy as np

from edge_local_refine import RULES, refine_candidate, detailed_structure
from bounded_edge_locator import array_hash, sample_integer
from run_edge_localization import (ROOT, BASE, OUT as E0, read, digest, write_new, hashes,
                                   verify_hashes, canvas, oracle_foreground)

OUT = BASE / 'edge-localization-e1'
CONTRACT = dict(version='E1-observed-local-line-1', upstream='frozen E0 A candidates, byte-identical',
    source_images_max=304, coarse_records=417, valid_local_refinements_max=373,
    fullframe_localization_calls=0, fullframe_otsu=False, model_forwards=0,
    validation84_reads=0, heldout112_reads=0, rules=RULES,
    local_threshold='single existing otsu32 per original-size grayscale polarity; no sweep',
    geometry='observed connected ink groups; relative-height integer tests; rational fit; ties-even Q16',
    selection='all coarse candidates; exact Q16-corner dedup only; one structurally valid result required',
    overflow='any coarse component/fragment/line overflow or more than 32 unique frame geometries invalidates frame',
    boundary='frozen invalid coarse skipped; selected ink and final corners need one-pixel search margin',
    first_glyph='must contain observed component IDs; never inferred from next glyph or GT',
    structure='same frozen seven-zone segmentation and consistency; instrumented returns only',
    evaluation='after selection; full304, old251, upstream-missing64, E0 geometry domain; GT polygon IoU and clipping diagnostic',
    raw_cache='original coarse BGR and final sampled BGR, compressed; no image reread needed for inspection')


def prepare():
    if OUT.exists():
        raise FileExistsError(OUT)
    frozen = read(E0 / 'delivery-freeze.json')
    verify_hashes(frozen['artifacts'])
    identities = read(E0 / 'identities.json')
    rows = [read(E0 / 'frames' / f"{i['sample_index']:03d}.json") for i in identities]
    assert sum(len(r['entries']['A']['candidates']) for r in rows) == 417
    assert sum(c['boundary_pass'] for r in rows for c in r['entries']['A']['candidates']) == 373
    sources = [Path(__file__), Path(__file__).with_name('edge_local_refine.py'),
               Path(__file__).with_name('test_edge_local_refine.py'),
               Path(__file__).with_name('bounded_edge_locator.py'), Path(__file__).with_name('run_edge_localization.py'),
               ROOT / 'tools/blue_plate/baseline.py', ROOT / 'tools/blue_plate/geometry_sampler.py',
               ROOT / 'tmp/plate-research-20261018/easypr-plate-locate.cpp',
               ROOT / 'tmp/blue-plate-review/edge-reuse-research/openalpr/src/openalpr/textdetection/characteranalysis.cpp',
               ROOT / 'tmp/blue-plate-review/edge-reuse-research/openalpr/src/openalpr/textdetection/linefinder.cpp',
               E0 / 'delivery-freeze.json', BASE / 'edge-localization-e1-preparation/tests-final.json',
               ROOT / 'docs/validation/blue-plate/char-segment/edge-localization-e1-contract.md']
    OUT.mkdir()
    write_new(OUT / 'identities.json', identities)
    write_new(OUT / 'contract.json', CONTRACT)
    write_new(OUT / 'source-hashes.json', hashes(sources))
    write_new(OUT / 'preparation.json', dict(created_utc=datetime.now(timezone.utc).isoformat(),
              status='FROZEN_BEFORE_IMAGES', files=hashes([OUT / 'identities.json', OUT / 'contract.json', OUT / 'source-hashes.json']),
              source_image_reads=0, local_refinement_calls=0, model_forwards=0))
    print('Frozen 304 identities, 417 coarse records, 373 valid local refinements')


def evaluate(line, gt, zones):
    poly = np.array(line['points'], np.float32)
    gt = np.array(gt, np.float32)
    area = float(cv2.contourArea(gt))
    intersection, _ = cv2.intersectConvexConvex(poly, gt)
    intersection = min(area, max(0., float(intersection)))
    union = float(cv2.contourArea(poly))+area-intersection
    contained = all(cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0 for x, y in gt)
    clipping = []
    for name, polar_zones in zones.items():
        counts = []
        for sx, sy in polar_zones:
            # Convex polygon membership, vectorized independently of sampling.
            signs = []
            for a, b in zip(poly, np.roll(poly, -1, axis=0)):
                signs.append((b[0]-a[0])*(sy-a[1])-(b[1]-a[1])*(sx-a[0]))
            inside = np.all(np.array(signs) >= -1e-6, axis=0) | np.all(np.array(signs) <= 1e-6, axis=0)
            counts.append(dict(total=len(sx), outside=int((~inside).sum()), fraction=float((~inside).mean())))
        clipping.append(dict(polarity=name, zones=counts,
                            any_zone_over_15_percent=any(r['outside']*100 > 15*r['total'] for r in counts)))
    return dict(iou=intersection/union if union else 0., gt_full_containment=contained,
                corner_errors_px=np.linalg.norm(poly-gt, axis=1).tolist(),
                gt_area_outside_fraction=(area-intersection)/area,
                foreground_clipping_diagnostic=clipping, character_clipping_confirmed=None)


def select(refined):
    unique = {}
    frame_capacity_exceeded = False
    for coarse in refined:
        for line in coarse['refinements']:
            key = tuple(v for p in line['points_q16'] for v in p)
            if key not in unique:
                if len(unique) == 32:
                    frame_capacity_exceeded = True
                    continue
                unique[key] = dict(line, source_coarse_uids=[coarse['uid']])
            else:
                assert unique[key]['valid'] == line['valid']
                unique[key]['source_coarse_uids'].append(coarse['uid'])
    overflow = any(r['overflow'] for r in refined) or frame_capacity_exceeded
    ordered = [unique[k] for k in sorted(unique)]
    eligible = [i for i, line in enumerate(ordered) if line['valid']]
    chosen = eligible[0] if len(eligible) == 1 and not overflow else None
    return dict(status='overflow' if overflow else 'selected' if chosen is not None else 'ambiguity' if len(eligible) > 1 else 'no_valid_refinement',
                overflow=overflow, frame_geometry_overflow=frame_capacity_exceeded,
                unique_geometry_count_lower_bound=len(unique)+int(frame_capacity_exceeded),
                stored_geometry_count=len(unique), eligible_count=len(eligible),
                selected_index=chosen, hypotheses=ordered)


def metrics(rows):
    groups = {'all304': rows, 'old251': [r for r in rows if r['old_correct']],
              'upstream_missing64': [r for r in rows if r['upstream_missing']],
              'geometry_domain303': [r for r in rows if r['domain']['in_predeclared_geometry_domain']]}
    report = {}
    for name, group in groups.items():
        counts = Counter(frames=len(group))
        gained, lost, wrong_boxes, selected_ids = [], [], [], []
        for r in group:
            s = r['selection']
            counts[s['status']] += 1
            picked = None if s['selected_index'] is None else s['hypotheses'][s['selected_index']]
            success = picked is not None and picked['evaluation']['iou'] >= .5
            before = r['e0_selected_iou50']
            counts['selected_iou50'] += success
            counts['selected_iou70'] += picked is not None and picked['evaluation']['iou'] >= .7
            counts['selected_gt_full_containment'] += picked is not None and picked['evaluation']['gt_full_containment']
            counts['any_refined_iou50'] += any(h['evaluation']['iou'] >= .5 for h in s['hypotheses'])
            if picked:
                selected_ids.append(r['sample_index'])
                diagnostics = picked['evaluation']['foreground_clipping_diagnostic']
                counts['selected_clipping_diagnostic_over15'] += any(d['any_zone_over_15_percent'] for d in diagnostics)
                counts['selected_clipping_unknown'] += not diagnostics
            if success and not before:
                gained.append(r['sample_index'])
            if before and not success:
                lost.append(r['sample_index'])
            if picked and not success:
                wrong_boxes.append(r['sample_index'])
        report[name] = dict(counts=dict(counts), new_iou50_ids=gained, lost_e0_iou50_ids=lost,
                            selected_iou_below50_ids=wrong_boxes, selected_ids=selected_ids)
    return report


def run():
    verify_hashes(read(OUT / 'preparation.json')['files'])
    verify_hashes(read(OUT / 'source-hashes.json'))
    verify_hashes(read(E0 / 'delivery-freeze.json')['artifacts'])
    assert read(OUT / 'contract.json') == CONTRACT
    write_new(OUT / 'run-start.json', dict(started_utc=datetime.now(timezone.utc).isoformat(),
              source_reads_max=304, local_refinement_calls_max=373, fullframe_locator_calls=0, model_forwards=0))
    (OUT / 'frames').mkdir()
    (OUT / 'crops').mkdir()
    missing = set(read(E0 / 'coarse-coverage.json')['A']['ids']['neither'])
    assert len(missing) == 64
    rows, calls, diagnostics = [], 0, 0
    for index, identity in enumerate(read(OUT / 'identities.json')):
        e0 = read(E0 / 'frames' / f"{identity['sample_index']:03d}.json")
        raw = (ROOT / identity['path']).read_bytes()
        import hashlib
        assert hashlib.sha256(raw).hexdigest() == identity['source_sha256']
        source = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if source is None:
            raise ValueError('Cannot decode '+identity['path'])
        frame, transform = canvas(source)
        assert array_hash(frame) == e0['canvas_sha256'] and transform == e0['transform']
        refined, replays, cache = [], [], {}
        for coarse in e0['entries']['A']['candidates']:
            # Only E0 geometry and pixels enter the refiner, never its GT metrics.
            clean = {k: coarse[k] for k in ('uid', 'boundary_pass', 'expanded_box')}
            start = time.perf_counter()
            local = refine_candidate(frame, clean, cache)
            local['software_seconds'] = time.perf_counter()-start
            refined.append(local)
            calls += coarse['boundary_pass']
            if coarse['boundary_pass']:
                original, _ = sample_integer(frame, np.array(coarse['points']), integer_solver=True)
                assert array_hash(original) == coarse['patch_bgr_sha256']
                traced = detailed_structure(original)
                for old, new in zip(coarse['polarities'], traced):
                    for key in ('polarity', 'valid', 'segmentation_pass', 'rects', 'mask_sha256'):
                        assert old[key] == new[key], (identity['sample_index'], coarse['uid'], key)
                replays.append(dict(uid=coarse['uid'], structure=traced))
                diagnostics += 1
        selection = select(refined)
        # Evaluation begins only after the frozen, GT-free selection is finished.
        gt = e0['gt_points_evaluation_only']
        oracle, zones = oracle_foreground(frame, np.array(gt))
        assert oracle == e0['oracle_foreground_diagnostic']
        for local in refined:
            for line in local['refinements']:
                line['evaluation'] = evaluate(line, gt, zones)
        for line in selection['hypotheses']:
            line['evaluation'] = evaluate(line, gt, zones)
        old_selected = next((c for c in e0['entries']['A']['candidates'] if c['uid'] == e0['entries']['A']['selected_uid']), None)
        crop_path = OUT / 'crops' / f"{identity['sample_index']:03d}.npz"
        np.savez_compressed(crop_path, **cache)
        row = dict(identity, old_correct=e0['old_no_color_outcome'] == 'correct', domain=e0['domain'],
                   upstream_missing=identity['sample_index'] in missing,
                   e0_selected_iou50=old_selected is not None and old_selected['evaluation']['iou'] >= .5,
                   frozen_coarse_count=len(refined), refinements=refined, e0_structure_replays=replays,
                   selection=selection, crop_cache_sha256=digest(crop_path),
                   gt_points_evaluation_only=gt, oracle_foreground_diagnostic=oracle)
        write_new(OUT / 'frames' / f"{identity['sample_index']:03d}.json", row)
        rows.append(row)
        if (index+1) % 16 == 0 or index == 303:
            print(json.dumps(dict(frames=index+1, local_refinements=calls,
                                  statuses=dict(Counter(r['selection']['status'] for r in rows)))), flush=True)
    assert calls == diagnostics == 373 and sum(r['frozen_coarse_count'] for r in rows) == 417
    verify_hashes(read(OUT / 'source-hashes.json'))
    verify_hashes(read(E0 / 'delivery-freeze.json')['artifacts'])
    write_new(OUT / 'summary.json', dict(status='COMPLETE_LOCAL_ONLY', source_image_reads=304,
              frozen_coarse_records=417, local_refinement_calls=373, e0_diagnostic_replays=373,
              fullframe_locator_calls=0, model_forwards=0, validation84_reads=0, heldout112_reads=0,
              metrics=metrics(rows), files=hashes(sorted((OUT / 'frames').glob('*.json')))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    {'prepare': prepare, 'run': run}[parser.parse_args().action]()
