"""Independent record audit; no image decode, locator call, or model forward."""
from collections import Counter
import json
from pathlib import Path

import numpy as np

from run_edge_localization import (OUT, ROOT, read, verify_hashes, write_new,
                                   hashes, summarize)


def main():
    summary = read(OUT / 'summary.json')
    verify_hashes(summary['files'])
    verify_hashes(read(OUT / 'source-hashes.json'))
    assert summary['traditional_locator_calls'] == 608
    assert summary['model_forwards'] == summary['validation84_reads'] == summary['heldout112_reads'] == 0
    identities = read(OUT / 'identities.json')
    rows = [read(OUT / 'frames' / f"{i['sample_index']:03d}.json") for i in identities]
    assert len(rows) == 304 and len(summary['files']) == 304
    assert Counter(r['split'] for r in rows) == dict(train=228, tune=76)
    for identity, row in zip(identities, rows):
        assert all(row[k] == v for k, v in identity.items())
        for data in row['entries'].values():
            assert data['completed_components_match_opencv']
            assert data['bounded']['counters']['live_slots_at_end'] == 0
            assert not data['bounded']['overflow'] and not data['ambiguity']
            eligible = [c for c in data['candidates'] if c['boundary_pass'] and c['structural_pass']]
            assert data['selected_uid'] == (eligible[0]['uid'] if len(eligible) == 1 else None)
    assert summarize(rows) == summary['metrics']
    projection, coverage = {}, {}
    for entry in ('A', 'B'):
        failures, coverage_counts = Counter(), Counter()
        failure_ids, coverage_ids, ratios = {}, {}, []
        for row in rows:
            data = row['entries'][entry]
            matching = [c for c in data['candidates'] if c['evaluation']['iou'] >= .5]
            contains = any(c['evaluation']['gt_full_containment'] for c in data['candidates'])
            group = 'both' if matching and contains else 'iou50_only' if matching else 'contain_only' if contains else 'neither'
            coverage_counts[group] += 1
            coverage_counts['old_correct_'+group] += row['old_no_color_outcome'] == 'correct'
            coverage_ids.setdefault(group, []).append(row['sample_index'])
            oracle = any(p['polarity'] == 'light' and p['seven_zones'] for p in row['oracle_foreground_diagnostic']['polarities'])
            coverage_counts['matching_rejected_with_oracle_seven'] += bool(matching) and data['selected_uid'] is None and oracle
            for c in matching:
                for p in c['polarities']:
                    if p['valid']:
                        continue
                    valleys = [min(p['column_projection'][x-9:x+10]) for x in (34, 70, 101, 132, 163, 194)]
                    reason = 'valley_over8' if max(valleys) > 8 else 'zone_or_local_otsu_failure'
                    key = p['polarity']+'_'+reason
                    failures[key] += 1
                    failure_ids.setdefault(key, []).append(row['sample_index'])
                x0, y0, x1, y1 = c['expanded_box']
                points = np.array(row['gt_points_evaluation_only'])
                ratios.append([(x1-x0)/np.ptp(points[:, 0]), (y1-y0)/np.ptp(points[:, 1])])
            selected = next((c for c in data['candidates'] if c['uid'] == data['selected_uid']), None)
            if selected and not selected['evaluation']['gt_full_containment']:
                failure_ids.setdefault('selected_not_full_containment', []).append(row['sample_index'])
        projection[entry] = dict(failure_counts=dict(failures), ids=failure_ids,
                                matching_expanded_to_gt_extent_p50=np.median(ratios, axis=0).tolist())
        coverage[entry] = dict(counts=dict(coverage_counts), ids=coverage_ids)
    assert projection == read(OUT / 'projection-diagnosis.json')
    # The initial command used filesystem order; compare the identity sets.
    old_coverage = read(OUT / 'coarse-coverage.json')
    for entry in ('A', 'B'):
        assert coverage[entry]['counts'] == old_coverage[entry]['counts']
        assert {k: sorted(v) for k, v in coverage[entry]['ids'].items()} == {k: sorted(v) for k, v in old_coverage[entry]['ids'].items()}
    preserved = {}
    for name in ('no-color-gates', 'detector-integer-audit'):
        frozen = read(ROOT / f'tmp/blue-plate-char-segment/{name}/delivery-freeze.json')
        verify_hashes(frozen['artifacts'])
        preserved[name] = len(frozen['artifacts'])
    main_report = read(ROOT / 'tmp/blue-plate-edge-gradient-reference/report.json')
    verify_hashes(main_report['source_hashes'])
    verify_hashes(main_report['reference_hashes'])
    report = dict(status='PASS', frames=304, entry_records=608, exact_partition_matches=608,
                  reproducible_metrics=True, projection_and_coverage_recomputed=True,
                  old_artifact_counts_preserved=preserved, main_product_source_hashes_preserved=True,
                  image_reads=0, locator_calls=0, model_forwards=0,
                  inputs=hashes([OUT / 'summary.json', OUT / 'diagnosis.json',
                                 OUT / 'projection-diagnosis.json', OUT / 'coarse-coverage.json']))
    write_new(OUT / 'verification.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
