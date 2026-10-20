"""Review frozen development decisions and expose limits of the visual gate."""
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from diagnose_plate_structure import DEST, RULES, THRESHOLDS, structure, read, sha, write


def main():
    freeze = read(DEST/'protocol-before-evaluation.json')
    assert all(sha(Path(p)) == digest for p, digest in freeze['source_hashes'].items())
    artifacts = read(DEST/'artifacts.json')
    assert all(sha(DEST/name) == digest for name, digest in artifacts.items())
    rows = read(DEST/'records.json')
    assert len([r for r in rows if r['kind'] == 'positive']) == 304
    assert len([r for r in rows if r['kind'].startswith(('left20', 'right20', 'middle20'))]) == 912
    selected_checks = 0
    losses = []
    distributions = {}
    for row in rows:
        for key, chosen in row['selections'].items():
            level, rule = key.split('/')
            proposals = sorted([p for p in row['outputs'] if p['base_gate'] and p['ocr']['legal']
                and (rule == 'base' or p['structure']['rules'][rule])], key=lambda p:(-p['ocr']['score'], p['candidate_index']))
            expected = proposals[0] if proposals and proposals[0]['ocr']['score'] >= THRESHOLDS[level] else None
            assert (chosen['candidate_index'] if chosen else None) == (expected['candidate_index'] if expected else None)
            selected_checks += 1
        base = row['selections']['strict/base']
        if base:
            p = next(p for p in row['outputs'] if p['candidate_index'] == base['candidate_index'])
            if row['kind'] == 'positive' or row['kind'].startswith('middle20'):
                group = distributions.setdefault(row['kind'], {'global': [], 'local': []})
                for mode in group:
                    detail = p['structure']['projection'][mode]
                    group[mode].append([detail['min_cell_height'], detail['min_cell_white'], max(detail['valley_counts'])])
            if row['kind'] == 'positive' and row['selections']['strict/global_seven'] is None:
                detail = p['structure']['projection']['global']
                reason = 'valley' if max(detail['valley_counts']) > 8 else 'empty' if detail['min_cell_white'] == 0 else 'short' if detail['min_cell_height'] < 24 else 'wide' if max(c['width'] for c in detail['cells']) > 36 else 'other'
                losses.append(dict(sample_index=row['sample_index'], label=row['label'], candidate_index=p['candidate_index'],
                    reason=reason, global_detail=detail, local_detail=p['structure']['projection']['local'],
                    local_recovers=row['selections']['strict/local_seven'] is not None))
    percentiles = {}
    for kind, modes in distributions.items():
        percentiles[kind] = {mode: dict(samples=len(values),
            min_cell_height=np.percentile(np.array(values)[:, 0], [0, 25, 50, 75, 100]).tolist(),
            min_cell_white=np.percentile(np.array(values)[:, 1], [0, 25, 50, 75, 100]).tolist(),
            max_valley=np.percentile(np.array(values)[:, 2], [0, 25, 50, 75, 100]).tolist()) for mode, values in modes.items()}
    # Tall bars satisfy measured geometry although they are not seven glyphs.
    # This is a scope counterexample, not a full-chain false accept.
    bars = np.zeros((64, 224, 3), np.uint8)
    for x in [12, 46, 80, 111, 142, 173, 204]:
        bars[14:50, x:x+6] = 255
    flags, _ = structure(bars)
    assert flags['rules']['global_seven']
    missing = bars.copy()
    missing[:, :34] = 0
    missing_flags, _ = structure(missing)
    assert not missing_flags['rules']['global_seven']
    blank_flags, _ = structure(np.zeros_like(bars))
    assert not blank_flags['rules']['either_seven']
    cv2.imwrite(str(DEST/'counterexample-seven-bars.png'), bars)
    cv2.imwrite(str(DEST/'counterexample-missing-first.png'), missing)
    write(DEST/'additional-correct-rejections.json', losses)
    write(DEST/'distributions.json', dict(percentiles=[0, 25, 50, 75, 100], groups=percentiles))
    write(DEST/'verification.json', dict(frozen_sources_match=True, frozen_artifacts_match=True,
        independently_checked_selections=selected_checks, full_blank_rejected=True, missing_first_rejected=True,
        seven_bars_pass_structure=True, synthetic_counterexample_is_not_full_chain_false_accept=True,
        global_correct_losses=len(losses), loss_reasons=dict(Counter(r['reason'] for r in losses)),
        global_losses_recovered_by_local=sum(r['local_recovers'] for r in losses),
        verification_source_sha256=sha(Path(__file__))))
    # Freeze the preregistered simplest primary; alternatives stay comparisons.
    write(DEST/'candidate-freeze.json', dict(candidate_id='measured-seven-global-v1',
        rule='len(baseline.segment(fixed_224x64_BGR, global, projection-char).characters)==7, AND frozen LPRNet strict/native-color/boundary gates',
        requires_84_confirmation_approval=True, validation_run=False, heldout_read=0,
        threshold=THRESHOLDS['strict'], comparison_threshold=THRESHOLDS['comparison'],
        alternatives_evaluated=RULES[1:], chosen_before_evaluation=True,
        source_hashes=freeze['source_hashes'], artifact_hashes={name: sha(DEST/name) for name in
            ['protocol-before-evaluation.json', 'records.json', 'report.json', 'verification.json', 'distributions.json']}))
    print('PASS', selected_checks, 'selection checks;', len(losses), 'additional correct rejections;',
          dict(Counter(r['reason'] for r in losses)))
    print(percentiles)


if __name__ == '__main__':
    main()
