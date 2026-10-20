"""E1 fixed local character-line geometry, using observed ink only."""
import ast
from collections import Counter
from itertools import combinations
from fractions import Fraction

import numpy as np

from bounded_edge_locator import ROOT, PARAMETERS, STRUCTURE, array_hash, bounded_rle, sample_integer, reference_components
from geometry_sampler import rounded_ratio

RULES = dict(row_runs=128, active_labels=256, retained_components=256, fragments=64,
             unique_lines_per_polarity=16, frame_refinements=32,
             fragment_min_area=3, fragment_min_height=3,
             anchor_min_height=6, anchor_crop_height_min=.20, anchor_crop_height_max=.80,
             anchor_width_height_min=.06, anchor_width_height_max=.90,
             anchor_fill_min=.05, anchor_fill_max=.90, height_ratio_min=.65,
             slope_max=.0875, line_residual_height_max=.35,
             fragment_line_height_min=.15, fragment_line_height_max=1.30,
             fragment_line_area_min=.02, merge_gap_height_max=.10,
             merge_width_height_max=.85, group_width_height_max=.90,
             group_fill_min=.08, group_fill_max=.90, group_height_min=.65,
             group_height_max=1.30, pitch_min_factor=.45, pitch_max_factor=1.80,
             pad_x_span=.05, pad_y_height=.25, margin=1)


def gray_from_bgr(patch):
    v = patch.astype(np.uint16)
    return ((77*v[:, :, 2]+150*v[:, :, 1]+29*v[:, :, 0]) >> 8).astype(np.uint8)


def capture_return(result, line, scope):
    details = dict(return_line=line)
    if line == 363:
        reason = 'global_otsu_single_bin'
    elif line == 430:
        reason = 'projection_valley_over8'
        details.update(center=int(scope['center']), minimum=int(scope['minimum']), prior_cuts=scope['cuts'].copy())
    elif line == 438:
        reason = 'empty_zone' if len(scope['xx']) == 0 else 'zone_height_extent_below23'
        details.update(zone_index=len(scope['rects']), interval=[int(scope['left']), int(scope['right'])],
                       foreground=len(scope['xx']), height_extent=0 if not len(scope['xx']) else int(np.ptp(scope['yy'])))
    elif line == 442:
        reason = 'zone_width_over36' if scope['x1']-scope['x0'] > 36 else 'zone_height_below23'
        details.update(zone_index=len(scope['rects']), width=int(scope['x1']-scope['x0']), height=int(scope['y1']-scope['y0']))
    elif line == 453:
        reason = 'local_otsu_single_bin'
        details.update(zone_index=len(scope['chars']), rect=[int(scope[k]) for k in ('x', 'y', 'w', 'h')])
    elif line == 455:
        reason = 'segmentation_pass'
    else:
        raise AssertionError('Unexpected return in frozen projection-char path: '+str(line))
    return (*result, dict(reason=reason, **details))


def instrument_segment():
    path = ROOT / 'tools/blue_plate/baseline.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'segment')

    class Returns(ast.NodeTransformer):
        def visit_Return(self, node):
            node.value = ast.Call(func=ast.Name(id='_capture', ctx=ast.Load()),
                                  args=[node.value, ast.Constant(node.lineno),
                                        ast.Call(func=ast.Name(id='locals', ctx=ast.Load()), args=[], keywords=[])], keywords=[])
            return node

    function = Returns().visit(function)
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    scope = dict(STRUCTURE, _capture=capture_return)
    exec(compile(module, str(path), 'exec'), scope)
    return scope['segment']


DETAILED_SEGMENT = instrument_segment()


def detailed_structure(patch):
    gray = gray_from_bgr(patch)
    records = []
    for name, y in [('light', gray), ('dark', 255-gray)]:
        chars, mask, rects, failure = DETAILED_SEGMENT(np.repeat(y[:, :, None], 3, axis=2), 'global', 'projection-char')
        rects = [list(map(int, r)) for r in rects]
        row = dict(polarity=name, valid=False, segmentation_pass=len(chars) == 7,
                   rects=rects, mask_sha256=array_hash(mask), failure=failure)
        if len(chars) == 7:
            xs = [2*x+w-1 for x, _, w, _ in rects]
            ys = [2*y+h-1 for _, y, _, h in rects]
            d = 7*sum(x*x for x in xs)-sum(xs)**2
            a = 7*sum(x*y for x, y in zip(xs, ys))-sum(xs)*sum(ys)
            heights = [r[3] for r in rects]
            residuals = [abs(7*d*y-7*a*x-(sum(ys)*d-a*sum(xs))) for x, y in zip(xs, ys)]
            checks = dict(tilt_pass=d > 0 and abs(a)*80 <= 7*d,
                          height_consistency_pass=min(heights)*100 >= 65*max(heights),
                          residual_pass=d > 0 and max(residuals)*10 <= 3*max(heights)*2*7*d)
            row.update(checks, valid=all(checks.values()))
            if not row['valid']:
                row['failure'] = dict(reason='line_consistency', failed=[k for k, v in checks.items() if not v])
        records.append(row)
    return records


def dimensions(component):
    x0, y0, x1, y1 = component['box']
    return x1-x0, y1-y0


def merge_fragments(components, twice_height):
    """Left-to-right ink groups; never synthesize a missing character region."""
    groups = []
    for component in sorted(components, key=lambda c: (c['box'][0], c['box'][1], c['uid'])):
        group = dict(box=component['box'].copy(), area=component['area'], members=[component['uid']])
        if groups:
            prev = groups[-1]
            gap = group['box'][0]-prev['box'][2]
            union = [min(prev['box'][0], group['box'][0]), min(prev['box'][1], group['box'][1]),
                     max(prev['box'][2], group['box'][2]), max(prev['box'][3], group['box'][3])]
            if gap*20 <= twice_height and (union[2]-union[0])*40 <= 17*twice_height:
                prev['box'] = union
                prev['area'] += group['area']
                prev['members'] += group['members']
                continue
        groups.append(group)
    return groups


def line_geometry(groups, crop_box):
    xs = [Fraction(g['box'][0]+g['box'][2]-1, 2) for g in groups]
    ys = [Fraction(g['box'][1]+g['box'][3]-1, 2) for g in groups]
    heights = [dimensions(g)[1] for g in groups]
    gaps = [b-a for a, b in zip(xs, xs[1:])]
    ordered = sorted(gaps)
    pitch = (ordered[2]+ordered[3])/2
    if pitch <= 0 or any(not 9*pitch <= 20*gap <= 36*pitch for gap in gaps):
        return None, 'inconsistent_pitch'
    if 100*min(heights) < 65*max(heights):
        return None, 'inconsistent_group_height'
    if any(a['box'][2] > b['box'][0] for a, b in zip(groups, groups[1:])):
        return None, 'overlapping_groups'
    denominator = 7*sum(x*x for x in xs)-sum(xs)**2
    slope = (7*sum(x*y for x, y in zip(xs, ys))-sum(xs)*sum(ys))/denominator
    intercept = (sum(ys)-slope*sum(xs))/7
    if abs(slope)*80 > 7:
        return None, 'line_slope'
    if max(abs(y-slope*x-intercept) for x, y in zip(xs, ys))*10 > 3*max(heights):
        return None, 'line_residual'
    width, height = crop_box[2]-crop_box[0], crop_box[3]-crop_box[1]
    if any(min(g['box'][0], g['box'][1], width-g['box'][2], height-g['box'][3]) < 1 for g in groups):
        return None, 'observed_ink_touches_search_boundary'
    left, right = min(g['box'][0] for g in groups), max(g['box'][2]-1 for g in groups)
    pad_x = Fraction(right-left+1, 20)
    left, right = left-pad_x, right+pad_x
    offsets = [y-slope*x-intercept for g in groups
               for x in (g['box'][0], g['box'][2]-1) for y in (g['box'][1], g['box'][3]-1)]
    pad_y = Fraction(sorted(heights)[3], 4)
    top, bottom = min(offsets)-pad_y, max(offsets)+pad_y
    points = [[left, slope*left+intercept+top], [right, slope*right+intercept+top],
              [right, slope*right+intercept+bottom], [left, slope*left+intercept+bottom]]
    # Do not borrow unseen pixels outside the local search when claiming completeness.
    if min(p[0] for p in points) < 1 or max(p[0] for p in points) > width-2 or min(p[1] for p in points) < 1 or max(p[1] for p in points) > height-2:
        return None, 'refined_margin_outside_search'
    points = [[v+crop_box[i] for i, v in enumerate(p)] for p in points]
    q16 = np.array([[rounded_ratio(v.numerator*65536, v.denominator) for v in p] for p in points], np.int64)
    return dict(points_q16=q16.tolist(), points=(q16/65536).tolist(), slope=float(slope),
                slope_exact=[slope.numerator, slope.denominator],
                observed_groups=groups, source_component_uids=sorted(u for g in groups for u in g['members'])), 'geometry_pass'


def polarity_lines(gray, polarity, box):
    mask = STRUCTURE['otsu32'](gray)
    if mask is None:
        return dict(polarity=polarity, status='local_otsu_single_bin', lines=[], overflow=False)
    h, w = gray.shape
    params = dict(PARAMETERS, row_runs=128, active_labels=256, candidates=256,
                  min_width=1, max_width=w, min_height=3, max_height=h,
                  aspect_min_num=0, aspect_max_num=100000)
    bounded = bounded_rle(mask, params)
    record = dict(polarity=polarity, mask_sha256=array_hash(mask), ccl=bounded,
                  lines=[], overflow=not bounded['valid'], status='searching')
    if not bounded['valid']:
        record['status'] = 'component_capacity_overflow'
        return record
    expected = reference_components(mask)
    actual = sorted([dict(box=c['box'], area=c['area']) for c in bounded['components']], key=lambda c: (c['box'], c['area']))
    assert actual == expected, 'Local bounded partition differs from independent OpenCV'
    record['opencv_partition_match'] = True
    record['search_boundary_component_uids'] = [c['uid'] for c in bounded['candidates']
        if min(c['box'][0], c['box'][1], w-c['box'][2], h-c['box'][3]) < 1]
    fragments = [c for c in bounded['candidates'] if c['area'] >= 3 and dimensions(c)[1]*5 <= 4*h
                 and dimensions(c)[0]*10 <= 9*h]
    record['retained_fragment_count'] = len(fragments)
    if len(fragments) > 64:
        record.update(status='fragment_capacity_overflow', overflow=True)
        return record
    anchors = [c for c in fragments if dimensions(c)[1] >= 6 and dimensions(c)[1]*5 >= h
               and dimensions(c)[0]*50 >= 3*dimensions(c)[1] and dimensions(c)[0]*10 <= 9*dimensions(c)[1]
               and c['area']*20 >= dimensions(c)[0]*dimensions(c)[1]
               and c['area']*10 <= 9*dimensions(c)[0]*dimensions(c)[1]]
    record['anchor_count'] = len(anchors)
    rejects, seen = Counter(), set()
    pair_count = 0
    for one, two in combinations(anchors, 2):
        pair_count += 1
        _, h1 = dimensions(one)
        _, h2 = dimensions(two)
        if min(h1, h2)*100 < 65*max(h1, h2):
            rejects['pair_height'] += 1
            continue
        x1, y1 = [one['box'][i]+one['box'][i+2]-1 for i in (0, 1)]
        x2, y2 = [two['box'][i]+two['box'][i+2]-1 for i in (0, 1)]
        dx, dy = x2-x1, y2-y1
        if dx == 0 or abs(dy)*80 > 7*abs(dx):
            rejects['pair_slope'] += 1
            continue
        twice_height = h1+h2
        members = []
        for c in fragments:
            cw, ch = dimensions(c)
            cx, cy = [c['box'][i]+c['box'][i+2]-1 for i in (0, 1)]
            if (ch*40 >= 3*twice_height and ch*20 <= 13*twice_height and c['area']*200 >= twice_height**2
                    and abs((cy-y1)*dx-dy*(cx-x1))*20 <= 7*twice_height*abs(dx)):
                members.append(c)
        groups = merge_fragments(members, twice_height)
        valid = [g for g in groups if dimensions(g)[1]*40 >= 13*twice_height and dimensions(g)[1]*20 <= 13*twice_height
                 and dimensions(g)[0]*100 >= 3*twice_height and dimensions(g)[0]*20 <= 9*twice_height
                 and g['area']*25 >= 2*dimensions(g)[0]*dimensions(g)[1]
                 and g['area']*10 <= 9*dimensions(g)[0]*dimensions(g)[1]]
        if len(valid) < 7:
            rejects['fewer_than_seven_observed_groups'] += 1
            continue
        for start in range(len(valid)-6):
            seven = valid[start:start+7]
            signature = tuple(tuple(sorted(g['members'])) for g in seven)
            if signature in seen:
                continue
            geometry, reason = line_geometry(seven, box)
            rejects[reason] += 1
            if geometry is None:
                continue
            if len(record['lines']) == 16:
                record.update(status='line_capacity_overflow', overflow=True, pair_reasons=dict(rejects), pair_count=pair_count)
                return record
            seen.add(signature)
            record['lines'].append(geometry)
    record.update(status='lines_found' if record['lines'] else 'no_observed_seven_group_line',
                  pair_reasons=dict(rejects), pair_count=pair_count)
    return record


def refine_candidate(frame, coarse, cache=None):
    if not coarse['boundary_pass']:
        return dict(uid=coarse['uid'], status='frozen_coarse_boundary_reject', polarities=[], refinements=[], overflow=False)
    x0, y0, x1, y1 = coarse['expanded_box']
    patch = frame[y0:y1, x0:x1]
    if cache is not None:
        cache[f"coarse_{coarse['uid']}"] = patch
    gray = gray_from_bgr(patch)
    polarities = [polarity_lines(y, name, coarse['expanded_box']) for name, y in [('light', gray), ('dark', 255-gray)]]
    refinements = {}
    overflow = any(p['overflow'] for p in polarities)
    if not overflow:
        for polarity in polarities:
            for line in polarity['lines']:
                signature = tuple(v for point in line['points_q16'] for v in point)
                if signature in refinements:
                    refinements[signature]['source_polarities'].append(polarity['polarity'])
                    continue
                original_color, matrix = sample_integer(frame, np.array(line['points']), integer_solver=True)
                if cache is not None:
                    cache[f"refined_{coarse['uid']}_{len(refinements)}"] = original_color
                details = detailed_structure(original_color)
                refinements[signature] = dict(line, source_polarities=[polarity['polarity']],
                    original_bgr_sha256=array_hash(original_color), inverse_q32=matrix.tolist(),
                    structure=details, valid=any(p['valid'] for p in details))
    return dict(uid=coarse['uid'], status='overflow' if overflow else 'refined' if refinements else 'no_local_line',
                original_crop_sha256=array_hash(patch), polarities=polarities,
                refinements=list(refinements.values()), overflow=overflow)
