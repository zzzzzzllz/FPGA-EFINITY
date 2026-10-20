"""Prepare and run the fixed 304-frame A/B experiment; no model inference."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import cv2
import numpy as np

from bounded_edge_locator import (ROOT, PARAMETERS, STRUCTURE, array_hash,
                                  reference_gradients, locate_from_gx, sample_integer)

BASE = ROOT / 'tmp/blue-plate-char-segment'
OUT = BASE / 'edge-localization-e0'
MANIFEST = BASE / 'experiment/dev-manifest.json'
OLD = BASE / 'no-color-gates/frame-records.json'
SAMPLES = ROOT / 'tmp/blue-plate-normal-g1/full-dual-local-geometry/samples.json'
MAIN_REFERENCE = ROOT / 'tools/blue_plate/edge_reference/reference.py'
MAIN_REPORT = ROOT / 'tmp/blue-plate-edge-gradient-reference/report.json'
CONTRACT = dict(
    version='E0-fixed-A-B-1', frames=304, calls_per_entry=304, total_locator_calls=608,
    model_forwards=0, validation84_reads=0, heldout112_reads=0,
    entries={'A': 'DDR luma -> median bypass -> Gaussian 3x3 -> signed main Gx',
             'B': 'DDR luma -> signed raw Gx before median'},
    main_reference_config=0x6038, main_reference_recognition=False,
    parameters=PARAMETERS, canvas=[1280, 720], resize='INTER_AREA; Python round; centered black padding',
    edge='abs signed Gx > 56; clear outermost row/column',
    close='17x3 dilation then erosion; zero padding',
    crop='expanded half-open bbox; pixel-center corners; Q32/Q5 original BGR 224x64',
    selection='exactly one boundary-valid candidate passes either grayscale polarity; otherwise reject',
    roi_structure='existing 32-bin Otsu / projection-char; both polarities; fixed line/height checks',
    fullframe_otsu=False, source_image_reads_max=304,
    domain=dict(width=[80, 640], height=[20, 160], aspect=[2.3, 6], slope_abs_max=0.0875,
                boundary_margin=1, geometry='GT corner axis-aligned extent and both long-edge slopes',
                visibility='unknown; no manual clear/unoccluded annotation',
                single_plate='one annotated plate; other visible plates not manually ruled out'),
    metrics=dict(iou_thresholds=[0.5, 0.7], iou='expanded candidate polygon vs GT quadrilateral',
                 full_containment='all four GT pixel-center corners inside candidate pixel-center rectangle',
                 clipping='report GT-ROI structure foreground outside candidate; >15% in any zone flags diagnostic',
                 clipping_is_ground_truth=False),
    execution_cost='A may require another fixed-profile job/DDR read; B raw tap is profile-stable; neither has verified throughput',
    gate='main exact RTL synthetic validation and local synthetic arithmetic crosscheck must pass before full images')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, data):
    with path.open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def hashes(paths):
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}


def verify_hashes(records):
    for name, expected in records.items():
        if digest(ROOT / name) != expected:
            raise ValueError('Frozen source changed: ' + name)


def prepare():
    if OUT.exists():
        raise FileExistsError('Preparation already exists; do not overwrite a frozen experiment')
    identities = {}
    for r in read(MANIFEST)['records']:
        assert r['original_split'] == 'development'
        item = {k: r[k] for k in ('sample_index', 'path', 'source_sha256', 'split', 'original_split')}
        assert item['split'] in ('train', 'tune')
        if r['sample_index'] in identities:
            assert identities[r['sample_index']] == item
        identities[r['sample_index']] = item
    old = {r['sample_index']: r for r in read(OLD)}
    assert len(identities) == 304 and set(identities) == set(old)
    assert sum(r['no_color']['outcome'] == 'correct' for r in old.values()) == 251
    assert Counter(r['split'] for r in identities.values()) == {'train': 228, 'tune': 76}
    # Filter the mixed metadata container before consulting its identity/GT fields.
    selected = {i: r for i, r in enumerate(read(SAMPLES)) if i in identities}
    for i, r in selected.items():
        assert r['split'] == 'development'
        assert (r['path'], r['sha256']) == (identities[i]['path'], identities[i]['source_sha256'])
    source_files = [Path(__file__), Path(__file__).with_name('bounded_edge_locator.py'),
                    Path(__file__).with_name('test_bounded_edge_locator.py'),
                    Path(__file__).with_name('test_edge_localization_runner.py'),
                    ROOT / 'tools/blue_plate/geometry_sampler.py', ROOT / 'tools/blue_plate/baseline.py',
                    MANIFEST, OLD, SAMPLES, BASE / 'edge-localization-e0-preparation/capacity-tests.json',
                    BASE / 'edge-localization-e0-preparation/runner-tests.json',
                    ROOT / 'docs/validation/blue-plate/char-segment/edge-localization-e0-contract.md']
    OUT.mkdir()
    write_new(OUT / 'identities.json', [identities[i] for i in sorted(identities)])
    write_new(OUT / 'contract.json', CONTRACT)
    write_new(OUT / 'source-hashes.json', hashes(source_files))
    write_new(OUT / 'preparation.json', dict(status='PREPARED_WAITING_EXACT_REFERENCE',
              created_utc=datetime.now(timezone.utc).isoformat(), image_reads=0, locator_calls=0,
              model_forwards=0, files=hashes([OUT / 'identities.json', OUT / 'contract.json', OUT / 'source-hashes.json'])))
    print('Prepared 304 identities, fixed A/B contract, zero image/model reads', flush=True)


def check_reference():
    verify_hashes(read(OUT / 'preparation.json')['files'])
    verify_hashes(read(OUT / 'source-hashes.json'))
    report = read(MAIN_REPORT)
    assert report['status'] == 'PASS' and report['jobs'] > 0
    # The validated implementation must be the exact reference now imported.
    ref_key = MAIN_REFERENCE.relative_to(ROOT).as_posix()
    assert report['reference_hashes'][ref_key] == digest(MAIN_REFERENCE)
    spec = importlib.util.spec_from_file_location('main_edge_reference', MAIN_REFERENCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rng = np.random.default_rng(20261019)
    cases = []
    for h, w in [(4, 6), (12, 16), (6, 1280), (720, 1280)]:
        bgr = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        bgr[0, 0] = [255, 0, 0]
        bgr[-1, -1] = [0, 0, 255]
        expected = module.compute(bgr[:, :, ::-1], config=0x6038, recognition=False)
        actual = reference_gradients(bgr)
        for entry in ('A', 'B'):
            assert np.array_equal(actual[entry], expected[entry.lower()+'_gx'])
        cases.append(dict(shape=[h, w], bgr_sha256=array_hash(bgr),
                          gradients={k: array_hash(v) for k, v in actual.items()}))
    write_new(OUT / 'gradient-crosscheck.json', dict(status='PASS', synthetic_cases=cases,
              image_reads=0, model_forwards=0, exact_reference_files=hashes([MAIN_REFERENCE, MAIN_REPORT]),
              local_reference_sha256=digest(Path(__file__).with_name('bounded_edge_locator.py'))))
    print('Exact main reference and local A/B agree on all synthetic pixels', flush=True)


def canvas(bgr):
    h, w = bgr.shape[:2]
    scale = min(1280/w, 720/h)
    nw, nh = round(w*scale), round(h*scale)
    dx, dy = (1280-nw)//2, (720-nh)//2
    frame = np.zeros((720, 1280, 3), np.uint8)
    frame[dy:dy+nh, dx:dx+nw] = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)
    return frame, dict(source_wh=[w, h], resized_wh=[nw, nh], offset_xy=[dx, dy])


def ground_truth(sample, transform):
    w, h = transform['source_wh']
    nw, nh = transform['resized_wh']
    dx, dy = transform['offset_xy']
    points = np.array(sample['points'], np.float64)[[2, 3, 0, 1]]
    points = points * [nw/w, nh/h] + [dx, dy]
    extent = points.max(axis=0)-points.min(axis=0)
    width, height = extent.tolist()
    slopes = []
    for left, right in [(0, 1), (3, 2)]:
        delta = points[right]-points[left]
        slopes.append(None if delta[0] <= 0 else float(delta[1]/delta[0]))
    in_domain = (80 <= width <= 640 and 20 <= height <= 160 and 2.3*height <= width <= 6*height
                 and all(v is not None and abs(v) <= 0.0875 for v in slopes)
                 and points[:, 0].min() >= 1 and points[:, 0].max() <= 1278
                 and points[:, 1].min() >= 1 and points[:, 1].max() <= 718)
    return points, dict(in_predeclared_geometry_domain=bool(in_domain), width=width, height=height,
                        long_edge_slopes=slopes, clear_unoccluded=None, single_visible_plate=None)


def oracle_foreground(frame, points):
    """Evaluation-only masks. They never enter candidate generation or selection."""
    patch, matrix = sample_integer(frame, points, integer_solver=True)
    gray = ((77*patch[:, :, 2].astype(np.uint16)+150*patch[:, :, 1].astype(np.uint16)+
             29*patch[:, :, 0].astype(np.uint16)) >> 8).astype(np.uint8)
    evidence, zones = [], {}
    for name, y in [('light', gray), ('dark', 255-gray)]:
        chars, mask, rects = STRUCTURE['segment'](np.repeat(y[:, :, None], 3, axis=2), 'global', 'projection-char')
        evidence.append(dict(polarity=name, seven_zones=len(chars) == 7,
                             rects=[list(map(int, r)) for r in rects], mask_sha256=array_hash(mask)))
        if len(chars) != 7:
            continue
        zones[name] = []
        for x, yy, w, h in rects:
            py, px = np.where(mask[yy:yy+h, x:x+w])
            px, py = px.astype(np.int64)+x, py.astype(np.int64)+yy
            den = matrix[2, 0]*px+matrix[2, 1]*py+matrix[2, 2]
            assert np.all(den > 0)
            coords = [(matrix[j, 0]*px+matrix[j, 1]*py+matrix[j, 2])/den for j in range(2)]
            zones[name].append(coords)
    return dict(patch_sha256=array_hash(patch), polarities=evidence,
                confirmed_character_visibility=None), zones


def candidate_metrics(candidate, points, zones):
    x0, y0, x1, y1 = candidate['expanded_box']
    polygon = np.array([[x0, y0], [x1-1, y0], [x1-1, y1-1], [x0, y1-1]], np.float32)
    gt = points.astype(np.float32)
    area = float(cv2.contourArea(gt))
    intersection, _ = cv2.intersectConvexConvex(polygon, gt)
    intersection = min(area, max(0., float(intersection)))
    union = float(cv2.contourArea(polygon))+area-intersection
    contains = bool(np.all((points[:, 0] >= x0) & (points[:, 0] <= x1-1) &
                           (points[:, 1] >= y0) & (points[:, 1] <= y1-1)))
    clipping = []
    for name, polar_zones in zones.items():
        lost = []
        for sx, sy in polar_zones:
            outside = (sx < x0) | (sx > x1-1) | (sy < y0) | (sy > y1-1)
            lost.append(dict(total=len(sx), outside=int(outside.sum()), fraction=float(outside.mean())))
        clipping.append(dict(polarity=name, zones=lost, any_zone_over_15_percent=any(r['outside']*100 > 15*r['total'] for r in lost)))
    distances = np.linalg.norm(polygon-points, axis=1)
    return dict(iou=intersection/union if union else 0., gt_full_containment=contains,
                gt_area_outside_fraction=(area-intersection)/area if area else None,
                corner_errors_px=distances.tolist(), mean_corner_error_px=float(distances.mean()),
                foreground_clipping_diagnostic=clipping, character_clipping_confirmed=None)


def summarize(rows):
    result = {}
    for name, subset in [('all304', rows), ('geometry_domain', [r for r in rows if r['domain']['in_predeclared_geometry_domain']]),
                         ('old251_correct', [r for r in rows if r['old_no_color_outcome'] == 'correct'])]:
        result[name] = {}
        for entry in ('A', 'B'):
            count = Counter(frames=len(subset))
            losses, containment_losses, seconds, candidate_counts = [], [], [], []
            polarity_counts = Counter()
            for row in subset:
                data = row['entries'][entry]
                count[data['status']] += 1
                seconds.append(data.get('software_seconds', 0))
                candidate_counts.append(len(data['candidates']))
                for candidate in data['candidates']:
                    for polarity in candidate['polarities']:
                        polarity_counts[polarity['polarity']+'_evaluated'] += 1
                        polarity_counts[polarity['polarity']+'_passed'] += polarity['valid']
                selected = next((c for c in data['candidates'] if c['uid'] == data['selected_uid']), None)
                for tag, candidates in [('any', data['candidates']), ('selected', [selected] if selected else [])]:
                    for threshold in (.5, .7):
                        count[f'{tag}_iou{int(threshold*100)}'] += any(c['evaluation']['iou'] >= threshold for c in candidates)
                    count[tag+'_gt_full_containment'] += any(c['evaluation']['gt_full_containment'] for c in candidates)
                if selected is None or selected['evaluation']['iou'] < .5:
                    losses.append(row['sample_index'])
                if selected is None or not selected['evaluation']['gt_full_containment']:
                    containment_losses.append(row['sample_index'])
                for event in data['bounded']['overflow']:
                    count['overflow_'+event['kind']] += 1
                if selected:
                    diagnostics = selected['evaluation']['foreground_clipping_diagnostic']
                    count['selected_clipping_diagnostic_unknown'] += not diagnostics
                    count['selected_clipping_any_polarity_over15'] += any(d['any_zone_over_15_percent'] for d in diagnostics)
            result[name][entry] = dict(counts=dict(count), localization_loss_iou50_ids=losses,
                 gt_full_containment_loss_ids=containment_losses, polarities=dict(polarity_counts),
                 candidate_count_total=sum(candidate_counts), candidate_count_max=max(candidate_counts, default=0),
                 software_seconds_p50_p95_max=np.percentile(seconds, [50, 95, 100]).tolist() if seconds else [])
    return result


def run():
    verify_hashes(read(OUT / 'preparation.json')['files'])
    verify_hashes(read(OUT / 'source-hashes.json'))
    assert read(OUT / 'contract.json') == CONTRACT
    proof = read(OUT / 'gradient-crosscheck.json')
    assert proof['status'] == 'PASS'
    verify_hashes(proof['exact_reference_files'])
    assert proof['local_reference_sha256'] == digest(Path(__file__).with_name('bounded_edge_locator.py'))
    identities = read(OUT / 'identities.json')
    ids = {r['sample_index'] for r in identities}
    selected_metadata = {i: r for i, r in enumerate(read(SAMPLES)) if i in ids}
    old = {r['sample_index']: r for r in read(OLD)}
    write_new(OUT / 'run-start.json', dict(started_utc=datetime.now(timezone.utc).isoformat(),
              expected_frames=304, expected_calls=608, proof_sha256=digest(OUT / 'gradient-crosscheck.json')))
    records_dir = OUT / 'frames'
    records_dir.mkdir()
    rows, calls = [], 0
    for index, identity in enumerate(identities):
        # One source read, verified before decode. No other dataset path is opened.
        raw = (ROOT / identity['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == identity['source_sha256']
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Image decode failed: '+identity['path'])
        frame, transform = canvas(image)
        gradients = reference_gradients(frame)
        entries = {}
        for entry in ('A', 'B'):
            start = time.perf_counter()
            entries[entry] = locate_from_gx(frame, gradients[entry])
            calls += 1
            entries[entry]['software_seconds'] = time.perf_counter()-start
            entries[entry]['gx_sha256'] = array_hash(gradients[entry])
        # Both algorithms are finished before accessing GT points or old outcomes.
        sample = selected_metadata[identity['sample_index']]
        points, domain = ground_truth(sample, transform)
        oracle, zones = oracle_foreground(frame, points)
        for data in entries.values():
            for c in data['candidates']:
                c['evaluation'] = candidate_metrics(c, points, zones)
        row = dict(identity, canvas_sha256=array_hash(frame), transform=transform,
                   gt_points_evaluation_only=points.tolist(), domain=domain, oracle_foreground_diagnostic=oracle,
                   old_no_color_outcome=old[identity['sample_index']]['no_color']['outcome'], entries=entries)
        write_new(records_dir / f"{identity['sample_index']:03d}.json", row)
        rows.append(row)
        if (index+1) % 16 == 0 or index == 303:
            print(json.dumps(dict(frames=index+1, locator_calls=calls, models=0,
                                  statuses={k: dict(Counter(r['entries'][k]['status'] for r in rows)) for k in ('A', 'B')})), flush=True)
    assert len(rows) == 304 and calls == 608
    verify_hashes(read(OUT / 'source-hashes.json'))
    write_new(OUT / 'summary.json', dict(status='COMPLETED_LOCALIZATION_ONLY', frames=304,
              traditional_locator_calls=calls, model_forwards=0, validation84_reads=0, heldout112_reads=0,
              metrics=summarize(rows), files=hashes(sorted(records_dir.glob('*.json')))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'check-reference', 'run'])
    action = parser.parse_args().action
    {'prepare': prepare, 'check-reference': check_reference, 'run': run}[action]()
