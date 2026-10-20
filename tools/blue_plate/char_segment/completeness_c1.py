"""Frozen C1 contextual evidence; no geometry proposal, cleanup, or OCR."""
import cv2
import numpy as np

from bounded_edge_locator import STRUCTURE, array_hash
from edge_local_refine import gray_from_bgr

RULES = dict(seed_overlap_num=1, seed_overlap_den=2, min_seed_pixels=3,
             width_height_num=3, width_height_den=2, min_height_num=1,
             min_height_den=2, max_height_factor=3, inside_percent=15,
             outside_percent=5, min_outside_pixels=3, extent_percent=10,
             min_extent_pixels=2, require_single_owner=True, reject_search_boundary=False)


def components(mask):
    return cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)


def edges_at_pixels(shape, points_q16, offset):
    y, x = np.indices(shape, dtype=np.int64)
    x = (x+offset[0])*65536
    y = (y+offset[1])*65536
    points = np.asarray(points_q16, np.int64)
    cross, scales = [], []
    for a, b in zip(points, np.roll(points, -1, axis=0)):
        dx, dy = b-a
        scale = int(max(abs(dx), abs(dy)))*65536
        if scale == 0:
            raise ValueError('Degenerate frozen edge')
        cross.append(dx*(y-a[1])-dy*(x-a[0]))
        scales.append(scale)
    # E1 order is TL, TR, BR, BL, so interior cross products are positive.
    return np.stack(cross), scales


def frozen_seeds(gray, line, polarity_record, polarity):
    old_mask = STRUCTURE['otsu32'](gray if polarity == 'light' else 255-gray)
    assert old_mask is not None
    assert array_hash(old_mask) == polarity_record['mask_sha256']
    _, labels, _, _ = components(old_mask)
    seeds = []
    for group in line['observed_groups']:
        members = [int(labels.flat[uid]) for uid in group['members']]
        assert all(members) and len(set(members)) == len(members)
        seed = np.isin(labels, members)
        y, x = np.where(seed)
        assert int(seed.sum()) == group['area']
        assert [int(x.min()), int(y.min()), int(x.max()+1), int(y.max()+1)] == group['box']
        seeds.append(seed)
    return seeds


def inspect_context(mask, seeds, height, points_q16, offset):
    count, labels, stats, _ = components(mask)
    cross, scales = edges_at_pixels(mask.shape, points_q16, offset)
    inside = np.all(cross >= 0, axis=0)
    extent = max(RULES['min_extent_pixels'], (height*RULES['extent_percent']+99)//100)
    overlaps = [np.bincount(labels[s], minlength=count) for s in seeds]
    records = []
    for cid in range(1, count):
        support = [int(o[cid]) for o in overlaps]
        if not any(support):
            continue
        owners = [i for i, (n, s) in enumerate(zip(support, seeds))
                  if n >= RULES['min_seed_pixels'] and n*2 >= int(s.sum())]
        x, y, w, h, area = map(int, stats[cid])
        pixels = labels == cid
        inside_n = int(np.count_nonzero(pixels & inside))
        edge_records = []
        for name, distances, scale in zip(('top', 'right', 'bottom', 'left'), cross, scales):
            outside = pixels & (distances < 0)
            n = int(outside.sum())
            max_cross = int(max(0, -distances[pixels].min()))
            edge_records.append(dict(edge=name, outside_pixels=n, max_extent_cross=max_cross,
                extent_denominator=scale, max_extent_px=max_cross/scale,
                substantial=n >= max(3, (area*5+99)//100) and max_cross >= extent*scale))
        unknown = []
        if len(owners) != 1:
            unknown.append('multiple_groups' if len(owners) > 1 else 'weak_seed_overlap')
        if w*2 > 3*height or h*2 < height or h > 3*height:
            unknown.append('not_isolated_character_scale')
        if x == 0 or y == 0 or x+w == mask.shape[1] or y+h == mask.shape[0]:
            unknown.append('search_boundary_component')
        if inside_n*100 < 15*area:
            unknown.append('insufficient_inside_ink')
        evidence = not unknown and any(e['substantial'] for e in edge_records)
        records.append(dict(label=cid, box=[x,y,x+w,y+h], area=area,
            seed_overlap_pixels=support, owners=owners, inside_pixels=inside_n,
            edges=edge_records, unknown_reasons=unknown, truncation_evidence=evidence))
    return dict(components=records, component_count=count-1, height=height,
                reject=any(r['truncation_evidence'] for r in records))


def raw_border(mask):
    _, _, stats, _ = components(mask)
    h, w = mask.shape
    return [dict(box=[int(x),int(y),int(x+bw),int(y+bh)], area=int(area))
            for x,y,bw,bh,area in stats[1:]
            if x == 0 or y == 0 or x+bw == w or y+bh == h]


def check(coarse, final, line, polarity_records, offset):
    gray, final_gray = gray_from_bgr(coarse), gray_from_bgr(final)
    height = sorted(g['box'][3]-g['box'][1] for g in line['observed_groups'])[3]
    reports = []
    for name in ('light', 'dark'):
        source = final_gray if name == 'light' else 255-final_gray
        target = gray if name == 'light' else 255-gray
        mask = STRUCTURE['otsu32'](source, target=target)
        raw = STRUCTURE['otsu32'](source)
        if mask is None:
            reports.append(dict(polarity=name, reject=False, status='single_bin_unknown'))
            continue
        record = dict(polarity=name, raw_final_mask_sha256=array_hash(raw),
                      context_mask_sha256=array_hash(mask), raw_border_components=raw_border(raw))
        if name not in line['source_polarities']:
            record.update(reject=False, status='no_frozen_line_association')
        else:
            seeds = frozen_seeds(gray, line, next(p for p in polarity_records if p['polarity'] == name), name)
            record.update(inspect_context(mask, seeds, height, line['points_q16'], offset))
            record['status'] = 'reject_truncation_evidence' if record['reject'] else 'unknown_no_truncation_evidence'
        reports.append(record)
    reject = any(p['reject'] for p in reports)
    return dict(status='reject_truncation_evidence' if reject else 'unknown_no_truncation_evidence',
                reject=reject, complete_certified=False, polarities=reports)
