"""Record/cache-only E1 verification, diagnosis, and a small inspection figure."""
from collections import Counter
from itertools import combinations
from pathlib import Path
import json

import numpy as np

from run_edge_local_e1 import OUT, E0, read, write_new, verify_hashes, metrics, select
from bounded_edge_locator import array_hash


def area(points):
    return abs(sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(points, points[1:]+points[:1])))/2


def polygon_iou(subject, clipper):
    polygon = [tuple(p) for p in subject]
    orientation = sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(clipper, clipper[1:]+clipper[:1]))
    sign = 1 if orientation >= 0 else -1
    for a, b in zip(clipper, clipper[1:]+clipper[:1]):
        cross = lambda p: sign*((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))
        source, polygon = polygon, []
        if not source:
            break
        for previous, current in zip(source[-1:]+source[:-1], source):
            cp, cc = cross(previous), cross(current)
            if (cp >= 0) != (cc >= 0):
                t = cp/(cp-cc)
                polygon.append((previous[0]+t*(current[0]-previous[0]), previous[1]+t*(current[1]-previous[1])))
            if cc >= 0:
                polygon.append(current)
    overlap = area(polygon) if len(polygon) >= 3 else 0.
    return overlap/(area(subject)+area(clipper)-overlap)


def main():
    summary = read(OUT / 'summary.json')
    verify_hashes(summary['files'])
    verify_hashes(read(OUT / 'source-hashes.json'))
    verify_hashes(read(E0 / 'delivery-freeze.json')['artifacts'])
    rows = [read(OUT / 'frames' / f"{r['sample_index']:03d}.json") for r in read(OUT / 'identities.json')]
    assert metrics(rows) == summary['metrics']
    counts, old_failures, matching_failures, new_structure_failures, polarity_status = [Counter() for _ in range(5)]
    ambiguity, losses, no_lines = [], [], []
    max_iou_error = 0.
    peak = Counter()
    times = []
    for row in rows:
        assert select(row['refinements']) == row['selection']
        e0 = read(E0 / 'frames' / f"{row['sample_index']:03d}.json")
        coarse_by_uid = {r['uid']: r for r in e0['entries']['A']['candidates']}
        assert set(coarse_by_uid) == {r['uid'] for r in row['refinements']}
        with np.load(OUT / 'crops' / f"{row['sample_index']:03d}.npz", allow_pickle=False) as cache:
            for coarse in row['refinements']:
                counts['coarse_'+coarse['status']] += 1
                times.append(coarse['software_seconds'])
                if coarse['status'] != 'frozen_coarse_boundary_reject':
                    assert array_hash(cache[f"coarse_{coarse['uid']}"]) == coarse['original_crop_sha256']
                    counts['cached_coarse_checked'] += 1
                for polarity in coarse['polarities']:
                    polarity_status[polarity['polarity']+'_'+polarity['status']] += 1
                    if 'ccl' in polarity:
                        counts['local_ccl_checks'] += 1
                        assert polarity['opencv_partition_match'] and polarity['ccl']['valid']
                        assert polarity['ccl']['counters']['live_slots_at_end'] == 0
                        for k in ('peak_row_runs', 'peak_active_slots', 'stored_candidates'):
                            peak[k] = max(peak[k], polarity['ccl']['counters'][k])
                        peak['fragments'] = max(peak['fragments'], polarity['retained_fragment_count'])
                        peak['anchor_pairs'] = max(peak['anchor_pairs'], polarity['pair_count'])
                    if not polarity['lines']:
                        no_lines.append(dict(sample_index=row['sample_index'], uid=coarse['uid'], polarity=polarity['polarity'],
                                             status=polarity['status'], anchors=polarity.get('anchor_count'),
                                             pair_reasons=polarity.get('pair_reasons', {})))
                for i, line in enumerate(coarse['refinements']):
                    assert array_hash(cache[f"refined_{coarse['uid']}_{i}"]) == line['original_bgr_sha256']
                    counts['cached_refined_checked'] += 1
                    exact = polygon_iou(line['points'], row['gt_points_evaluation_only'])
                    error = abs(exact-line['evaluation']['iou'])
                    max_iou_error = max(error, max_iou_error)
                    assert error < 5e-5
                    for p in line['structure']:
                        new_structure_failures[p['polarity']+'_'+p['failure']['reason']] += 1
            assert counts['cached_coarse_checked'] <= 373
        for coarse in row['e0_structure_replays']:
            for p in coarse['structure']:
                key = p['polarity']+'_'+p['failure']['reason']
                old_failures[key] += 1
                if coarse_by_uid[coarse['uid']]['evaluation']['iou'] >= .5:
                    matching_failures[key] += 1
        if row['selection']['status'] == 'ambiguity':
            lines = [r for r in row['selection']['hypotheses'] if r['valid']]
            pairwise = []
            for a, b in combinations(lines, 2):
                sa, sb = set(a['source_component_uids']), set(b['source_component_uids'])
                pairwise.append(dict(ink_jaccard=len(sa & sb)/len(sa | sb),
                                     box_iou=polygon_iou(a['points'], b['points']),
                                     differing_component_uids=sorted(sa ^ sb)))
            ambiguity.append(dict(sample_index=row['sample_index'], valid_lines=len(lines),
                same_coarse=len({u for line in lines for u in line['source_coarse_uids']}) == 1,
                same_ink_union=len({tuple(line['source_component_uids']) for line in lines}) == 1, pairs=pairwise))
        if row['sample_index'] in summary['metrics']['all304']['lost_e0_iou50_ids']:
            losses.append(dict(sample_index=row['sample_index'], status=row['selection']['status'],
                coarse_statuses=[r['status'] for r in row['refinements']],
                line_structure_reasons=[p['failure']['reason'] for r in row['refinements']
                                       for line in r['refinements'] for p in line['structure']]))
    assert counts['cached_coarse_checked'] == 373 and counts['local_ccl_checks'] == 746
    result = dict(status='PASS_RECORD_AND_CACHE_AUDIT', source_image_reads=0, local_refinement_calls=0, model_forwards=0,
        counts=dict(counts), local_capacity_peaks=dict(peak), independent_polygon_iou_max_error=max_iou_error,
        e0_all_coarse_failure_reasons=dict(old_failures), e0_matching_failure_reasons=dict(matching_failures),
        e1_structure_reasons=dict(new_structure_failures), local_polarity_status=dict(polarity_status),
        ambiguity=ambiguity, losses=losses, no_line_diagnostics=no_lines,
        local_software_seconds_p50_p95_max=np.percentile(times, [50, 95, 100]).tolist())
    write_new(OUT / 'audit.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('no_line_diagnostics', 'ambiguity')}, indent=2))
    figure(rows)


def figure(rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    # Predeclared inspection cases: a new success, ambiguity, and E0 losses.
    cases = [2, 18, 21, 112, 293]
    by_id = {r['sample_index']: r for r in rows}
    fig, axes = plt.subplots(len(cases), 3, figsize=(12, 10))
    for ri, sample_id in enumerate(cases):
        row = by_id[sample_id]
        e0 = read(E0 / 'frames' / f'{sample_id:03d}.json')
        # GT is used here only to display the diagnostic coarse region.
        old = max(e0['entries']['A']['candidates'], key=lambda c: c['evaluation']['iou'])
        local = next(r for r in row['refinements'] if r['uid'] == old['uid'])
        with np.load(OUT / 'crops' / f'{sample_id:03d}.npz', allow_pickle=False) as cache:
            if f"coarse_{old['uid']}" in cache:
                axes[ri, 0].imshow(cache[f"coarse_{old['uid']}"][:, :, ::-1])
                origin = np.array(old['expanded_box'][:2])
                axes[ri, 0].add_patch(Polygon(np.array(row['gt_points_evaluation_only'])-origin,
                    fill=False, edgecolor='lime', linewidth=1))
                for line in local['refinements'][:2]:
                    axes[ri, 0].add_patch(Polygon(np.array(line['points'])-origin, fill=False, edgecolor='orange', linewidth=1))
            axes[ri, 0].set_title(f"{sample_id}: coarse; GT green, E1 orange", fontsize=9)
            for ci in range(2):
                ax = axes[ri, ci+1]
                if ci < len(local['refinements']):
                    line = local['refinements'][ci]
                    ax.imshow(cache[f"refined_{old['uid']}_{ci}"][:, :, ::-1])
                    ax.set_title(f"hyp {ci}: valid={line['valid']}; IoU={line['evaluation']['iou']:.3f}", fontsize=9)
                else:
                    ax.text(.05, .5, 'No additional local geometry', fontsize=9)
        for ax in axes[ri]:
            ax.axis('off')
    fig.suptitle('E1 cached crops only; no source reread / OCR. Selection remains frozen.', fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / 'inspection.png', dpi=160)
    plt.close(fig)


if __name__ == '__main__':
    main()
