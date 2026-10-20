"""Fixed E0 localization primitives. No detector, color gate, OCR, or training."""
import ast
import hashlib
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools/blue_plate'))
from geometry_sampler import sample_integer

PARAMETERS = dict(threshold=56, close_width=17, close_height=3, row_runs=128,
                  active_labels=256, candidates=32, min_width=80, max_width=640,
                  min_height=20, max_height=160, aspect_min_num=23, aspect_max_num=60,
                  aspect_den=10, pad_x_num=4, pad_y_num=20, pad_den=100,
                  slope_num=7, slope_den=80, height_ratio_num=65, height_ratio_den=100,
                  residual_num=3, residual_den=10)


def array_hash(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def reference_gradients(bgr):
    """A/B arithmetic; the runner requires a crosscheck against the RTL reference."""
    if bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError('Expected uint8 BGR frame')
    v = bgr.astype(np.int32)
    y = (77 * v[:, :, 2] + 150 * v[:, :, 1] + 29 * v[:, :, 0] + 128) >> 8
    p = np.pad(y, 1, mode='edge')
    gauss = (p[:-2, :-2] + 2*p[:-2, 1:-1] + p[:-2, 2:] +
             2*p[1:-1, :-2] + 4*p[1:-1, 1:-1] + 2*p[1:-1, 2:] +
             p[2:, :-2] + 2*p[2:, 1:-1] + p[2:, 2:] + 8) >> 4
    result = {}
    for name, source in [('A', gauss), ('B', y)]:
        p = np.pad(source, 1, mode='edge')
        gx = p[:-2, 2:] + 2*p[1:-1, 2:] + p[2:, 2:] - p[:-2, :-2] - 2*p[1:-1, :-2] - p[2:, :-2]
        result[name] = gx.astype(np.int16)
    return result


def binary_axis(a, radius, axis, dilate):
    pads = [(0, 0), (0, 0)]
    pads[axis] = (radius, radius)
    padded = np.pad(a, pads, mode='constant', constant_values=False)
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2*radius+1, axis=axis)
    return windows.any(axis=-1) if dilate else windows.all(axis=-1)


def close_edges(gx):
    edge = np.abs(gx.astype(np.int32)) > PARAMETERS['threshold']
    edge[[0, -1], :] = False
    edge[:, [0, -1]] = False
    closed = edge
    for dilate in (True, False):
        closed = binary_axis(closed, 8, 1, dilate)
        closed = binary_axis(closed, 1, 0, dilate)
    return edge, closed


def geometry_ok(box, p):
    x0, y0, x1, y1 = box
    w, h = x1-x0, y1-y0
    return (p['min_width'] <= w <= p['max_width'] and p['min_height'] <= h <= p['max_height']
            and p['aspect_min_num']*h <= p['aspect_den']*w <= p['aspect_max_num']*h)


def bounded_rle(mask, parameters=PARAMETERS):
    """8-connected row RLE with fixed live slots, retirement, and fail-closed caps.

    Python lists below are an audit log, not extra hardware storage. The actual
    row lists, label slots, and candidate table have the stated hard capacities.
    """
    p = parameters
    parent = [-1] * p['active_labels']
    stats = [None] * p['active_labels']
    previous = []
    candidates, components, events = [], [], []
    overflow = []
    peak_labels = peak_runs = 0
    allocations = retirements = alias_reclaims = merges = 0
    comparisons = find_hops = 0
    width = mask.shape[1]

    def find(slot):
        nonlocal find_hops
        if parent[slot] < 0:
            raise AssertionError('Read of retired label')
        while parent[slot] != slot:
            find_hops += 1
            parent[slot] = parent[parent[slot]]
            slot = parent[slot]
        return slot

    for y in range(mask.shape[0] + 1):
        line = mask[y] if y < mask.shape[0] else np.zeros(width, bool)
        diff = np.diff(np.r_[False, line, False].astype(np.int8))
        starts, ends = np.flatnonzero(diff == 1), np.flatnonzero(diff == -1)
        assert len(starts) == len(ends)
        peak_runs = max(peak_runs, len(starts))
        if len(starts) > p['row_runs']:
            overflow.append(dict(kind='row_runs', row=y, observed=len(starts), capacity=p['row_runs']))
            break
        current = []
        for x0, x1 in zip(starts.tolist(), ends.tolist()):
            overlaps = []
            for a, b, label in previous:
                comparisons += 1
                # Half-open runs share an 8-neighbour if their ends meet.
                if a <= x1 and x0 <= b:
                    root = find(label)
                    if root not in overlaps:
                        overlaps.append(root)
            if not overlaps:
                free = next((i for i, v in enumerate(parent) if v < 0), None)
                if free is None:
                    overflow.append(dict(kind='active_labels', row=y, x=x0, observed=p['active_labels']+1, capacity=p['active_labels']))
                    break
                root = free
                parent[root] = root
                stats[root] = dict(uid=y*width+x0, box=[x0, y, x1, y+1], area=0,
                                   sum_x=0, sum_y=0, sum_xx=0, sum_xy=0, sum_yy=0)
                allocations += 1
                peak_labels = max(peak_labels, sum(v >= 0 for v in parent))
            else:
                root = min(overlaps)
                for other in overlaps:
                    if other == root:
                        continue
                    parent[other] = root
                    a, b = stats[root], stats[other]
                    a['uid'] = min(a['uid'], b['uid'])
                    a['box'] = [min(a['box'][0], b['box'][0]), min(a['box'][1], b['box'][1]),
                                max(a['box'][2], b['box'][2]), max(a['box'][3], b['box'][3])]
                    for key in ('area', 'sum_x', 'sum_y', 'sum_xx', 'sum_xy', 'sum_yy'):
                        a[key] += b[key]
                    merges += 1
            n = x1-x0
            sx = (x0+x1-1)*n//2
            square_sum = lambda t: t*(t+1)*(2*t+1)//6
            sxx = square_sum(x1-1)-square_sum(x0-1)
            s = stats[root]
            s['box'] = [min(s['box'][0], x0), min(s['box'][1], y), max(s['box'][2], x1), max(s['box'][3], y+1)]
            for key, value in [('area', n), ('sum_x', sx), ('sum_y', y*n), ('sum_xx', sxx), ('sum_xy', y*sx), ('sum_yy', y*y*n)]:
                s[key] += value
            current.append((x0, x1, root))
        if overflow and overflow[-1]['kind'] == 'active_labels':
            break
        # Resolve all row references before reusing aliases or finished roots.
        current = [(a, b, find(label)) for a, b, label in current]
        live = {label for _, _, label in current}
        roots = {find(i) for i, v in enumerate(parent) if v >= 0}
        retired = []
        for root in sorted(roots-live, key=lambda i: stats[i]['uid']):
            item = dict(stats[root], retired_row=y)
            components.append(item)
            retired.append(item['uid'])
            retirements += 1
            if geometry_ok(item['box'], p):
                stored = len(candidates) < p['candidates']
                item['candidate_stored'] = stored
                if stored:
                    candidates.append(item.copy())
                elif not any(e['kind'] == 'candidates' for e in overflow):
                    overflow.append(dict(kind='candidates', row=y, observed=p['candidates']+1, capacity=p['candidates']))
        freed_aliases = 0
        for i, v in enumerate(parent):
            if v >= 0 and i not in live:
                if v != i:
                    freed_aliases += 1
                parent[i] = -1
                stats[i] = None
        alias_reclaims += freed_aliases
        if retired or freed_aliases:
            events.append(dict(row=y, retired_component_uids=retired, aliases_reclaimed=freed_aliases,
                               live_labels_after_reclaim=len(live)))
        assert all(parent[i] == i for i in live)
        assert len(current) <= p['row_runs'] and len(candidates) <= p['candidates']
        previous = current
    return dict(valid=not overflow, overflow=overflow, candidates=candidates, components=components,
                retirement_events=events, counters=dict(peak_row_runs=peak_runs, peak_active_slots=peak_labels,
                allocations=allocations, retired_components=retirements, reclaimed_aliases=alias_reclaims,
                union_merges=merges, run_overlap_comparisons=comparisons, parent_hops=find_hops,
                live_slots_at_end=sum(v >= 0 for v in parent), stored_candidates=len(candidates)))


def reference_components(mask):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return sorted([dict(box=[int(x), int(y), int(x+w), int(y+h)], area=int(a))
                   for x, y, w, h, a in stats[1:]], key=lambda r: (r['box'], r['area']))


def load_structure_functions():
    path = ROOT / 'tools/blue_plate/baseline.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    wanted = {'otsu32', 'binary', 'segment'}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in nodes} == wanted
    scope = dict(np=np, cv2=cv2)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
    return scope


STRUCTURE = load_structure_functions()


def structure_evidence(patch):
    """Two fixed grayscale polarities; no OCR or color-derived selection."""
    y = ((patch[:, :, 2].astype(np.uint16)*77 + patch[:, :, 1].astype(np.uint16)*150 +
          patch[:, :, 0].astype(np.uint16)*29) >> 8).astype(np.uint8)
    rows = []
    for name, gray in [('light', y), ('dark', 255-y)]:
        # Passing a three-channel gray image preserves baseline's integer luma.
        # For equal channels, weights sum to 256, so gray is unchanged exactly.
        pseudo_bgr = np.repeat(gray[:, :, None], 3, axis=2)
        raw = STRUCTURE['otsu32'](gray)
        chars, mask, rects = STRUCTURE['segment'](pseudo_bgr, 'global', 'projection-char')
        rects = [list(map(int, r)) for r in rects]
        row = dict(polarity=name, valid=False, segmentation_pass=len(chars) == 7,
                   rects=rects, mask_sha256=array_hash(mask),
                   raw_border_foreground=None if raw is None else int(raw[0].sum()+raw[-1].sum()+raw[1:-1, 0].sum()+raw[1:-1, -1].sum()),
                   column_projection=mask.sum(axis=0).astype(int).tolist(),
                   foreground_per_zone=[int(mask[y0:y0+h, x:x+w].sum()) for x, y0, w, h in rects])
        if len(chars) == 7:
            xs = [2*x+w-1 for x, _, w, _ in rects]
            ys = [2*y0+h-1 for _, y0, _, h in rects]
            n = 7
            d = n*sum(x*x for x in xs)-sum(xs)**2
            a = n*sum(x*y0 for x, y0 in zip(xs, ys))-sum(xs)*sum(ys)
            heights = [r[3] for r in rects]
            residuals = [abs(n*d*y0 - n*a*x - (sum(ys)*d-a*sum(xs))) for x, y0 in zip(xs, ys)]
            tilt_ok = d > 0 and abs(a)*80 <= 7*d
            height_ok = min(heights)*100 >= 65*max(heights)
            # Coordinates are doubled: divide residual numerator by 2*n*d.
            residual_ok = d > 0 and max(residuals)*10 <= 3*max(heights)*2*n*d
            row.update(slope_numerator=a, slope_denominator=d, tilt_pass=tilt_ok,
                       height_consistency_pass=height_ok, residual_pass=residual_ok,
                       valid=tilt_ok and height_ok and residual_ok)
        rows.append(row)
    return rows


def locate_from_gx(frame, gx):
    edge, closed = close_edges(gx)
    bounded = bounded_rle(closed)
    reference = reference_components(closed)
    actual = sorted([dict(box=r['box'], area=r['area']) for r in bounded['components']], key=lambda r: (r['box'], r['area']))
    ccl_exact = actual == reference
    if not any(e['kind'] in ('row_runs', 'active_labels') for e in bounded['overflow']):
        assert ccl_exact, 'Bounded RLE disagrees with independent OpenCV partition'
    records = []
    for item in bounded['candidates']:
        x0, y0, x1, y1 = item['box']
        w, h = x1-x0, y1-y0
        px, py = (4*w+99)//100, (20*h+99)//100
        box = [x0-px, y0-py, x1+px, y1+py]
        points = [[box[0], box[1]], [box[2]-1, box[1]], [box[2]-1, box[3]-1], [box[0], box[3]-1]]
        margin = min(box[0], box[1], frame.shape[1]-box[2], frame.shape[0]-box[3])
        row = dict(item, expanded_box=box, points=points, boundary_margin=margin,
                   boundary_pass=margin >= 1, polarities=[], structural_pass=False)
        if bounded['valid'] and margin >= 1:
            patch, matrix = sample_integer(frame, np.array(points), integer_solver=True)
            row.update(patch_bgr_sha256=array_hash(patch), inverse_q32=matrix.tolist(), polarities=structure_evidence(patch))
            row['structural_pass'] = any(p['valid'] for p in row['polarities'])
        else:
            row['structure_skip_reason'] = 'capacity_overflow' if not bounded['valid'] else 'boundary'
        records.append(row)
    eligible = [r for r in records if r['structural_pass'] and r['boundary_pass']]
    selected = eligible[0] if bounded['valid'] and len(eligible) == 1 else None
    return dict(edge_sha256=array_hash(edge), closed_sha256=array_hash(closed),
                edge_pixels=int(edge.sum()), closed_pixels=int(closed.sum()), bounded=bounded,
                independent_opencv_components=reference, completed_components_match_opencv=ccl_exact,
                candidates=records, eligible_count=len(eligible), ambiguity=len(eligible) > 1,
                status='overflow' if not bounded['valid'] else 'selected' if selected else 'ambiguity' if len(eligible) > 1 else 'no_structural_candidate',
                selected_uid=None if selected is None else selected['uid'])
