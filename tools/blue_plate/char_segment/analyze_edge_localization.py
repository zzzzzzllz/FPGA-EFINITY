"""Analyze frozen E0 records without reading images or rerunning localization."""
from collections import Counter
import json

import numpy as np

from run_edge_localization import OUT, read, write_new, verify_hashes, candidate_metrics, hashes
from bounded_edge_locator import PARAMETERS, geometry_ok


def main():
    summary = read(OUT / 'summary.json')
    assert summary['status'] == 'COMPLETED_LOCALIZATION_ONLY'
    verify_hashes(summary['files'])
    verify_hashes(read(OUT / 'source-hashes.json'))
    identities = read(OUT / 'identities.json')
    records = [read(OUT / 'frames' / f"{r['sample_index']:03d}.json") for r in identities]
    assert len(records) == 304 and len({r['sample_index'] for r in records}) == 304
    breakdown, failures = {}, []
    for entry in ('A', 'B'):
        stages, reasons, structure = Counter(), Counter(), Counter()
        counters = []
        for row in records:
            data = row['entries'][entry]
            assert data['bounded']['valid'] == (len(data['bounded']['overflow']) == 0)
            assert data['eligible_count'] == sum(c['boundary_pass'] and c['structural_pass'] for c in data['candidates'])
            assert (data['selected_uid'] is not None) == (data['bounded']['valid'] and data['eligible_count'] == 1)
            assert len(data['candidates']) <= 32
            matching = [c for c in data['candidates'] if c['evaluation']['iou'] >= .5]
            boundary = [c for c in matching if c['boundary_pass']]
            structured = [c for c in boundary if c['structural_pass']]
            selected_match = [c for c in structured if c['uid'] == data['selected_uid']]
            for name, values in [('geometric_iou50', matching), ('boundary_iou50', boundary),
                                 ('structure_iou50', structured), ('selected_iou50', selected_match)]:
                stages[name] += bool(values)
            if selected_match:
                reason = 'selected_iou50'
            elif not data['bounded']['valid']:
                reason = 'capacity_overflow'
            elif not matching:
                reason = 'no_geometric_candidate_iou50'
            elif not boundary:
                reason = 'matching_candidates_boundary_rejected'
            elif not structured:
                reason = 'matching_candidates_structure_rejected'
            else:
                reason = 'multiple_structural_candidates'
            reasons[reason] += 1
            for c in boundary:
                for p in c['polarities']:
                    structure[p['polarity']+'_matching_candidates'] += 1
                    structure[p['polarity']+'_segmentation_pass'] += p['segmentation_pass']
                    for key in ('tilt_pass', 'height_consistency_pass', 'residual_pass', 'valid'):
                        structure[p['polarity']+'_'+key] += p.get(key, False)
                    structure['returned_rects_'+str(len(p['rects']))] += 1
            # GT-ranked component diagnostics are evaluation only, never output selection.
            best = None
            for component in data['bounded']['components']:
                x0, y0, x1, y1 = component['box']
                w, h = x1-x0, y1-y0
                px, py = (4*w+99)//100, (20*h+99)//100
                m = candidate_metrics(dict(expanded_box=[x0-px, y0-py, x1+px, y1+py]),
                                      np.array(row['gt_points_evaluation_only']), {})
                if best is None or m['iou'] > best['iou']:
                    best = dict(uid=component['uid'], box=component['box'], iou=m['iou'],
                                geometry_pass=geometry_ok(component['box'], PARAMETERS),
                                width_pass=80 <= w <= 640, height_pass=20 <= h <= 160,
                                aspect_pass=23*h <= 10*w <= 60*h)
            if reason == 'no_geometric_candidate_iou50':
                if best is not None and best['iou'] >= .5:
                    reasons['matching_component_removed_by_geometry'] += 1
                    for key in ('width_pass', 'height_pass', 'aspect_pass'):
                        reasons['matching_component_failed_'+key] += not best[key]
                else:
                    reasons['no_completed_component_iou50'] += 1
            counters.append(data['bounded']['counters'])
            failures.append(dict(sample_index=row['sample_index'], entry=entry, reason=reason,
                                 old_correct=row['old_no_color_outcome'] == 'correct',
                                 in_geometry_domain=row['domain']['in_predeclared_geometry_domain'],
                                 matching_uids=[c['uid'] for c in matching], best_component_diagnostic=best))
        breakdown[entry] = dict(stages=dict(stages), reasons=dict(reasons), matching_structure=dict(structure),
             counter_max={k: max(r[k] for r in counters) for k in counters[0]},
             counter_sum={k: sum(r[k] for r in counters) for k in counters[0]})
    write_new(OUT / 'diagnosis-records.json', failures)
    write_new(OUT / 'diagnosis.json', dict(status='PASS_RECORD_AUDIT', frames=304, entries=breakdown,
              source_images_read=0, new_locator_calls=0, model_forwards=0,
              inputs=hashes([OUT / 'summary.json', OUT / 'gradient-crosscheck.json'])))
    print(json.dumps(breakdown, indent=2))


if __name__ == '__main__':
    main()
