"""Read-only independent DP/selection checks of the frozen development comparison."""
import numpy as np

from experiment import ROOT, read_json, write_json, sha

OUT = ROOT/'tmp/blue-plate-char-segment/pretrained-new-rois'


def ctc_dp(logits, target):
    shifted = logits.astype(np.float64) - logits.max(axis=0)
    logp = shifted - np.log(np.exp(shifted).sum(axis=0))
    extended = [67]
    for c in target:
        extended.extend([c, 67])
    previous = np.full(len(extended), -np.inf)
    previous[0] = logp[67, 0]
    if target:
        previous[1] = logp[target[0], 0]
    for t in range(1, logits.shape[1]):
        current = np.full_like(previous, -np.inf)
        for s, c in enumerate(extended):
            value = previous[s]
            if s:
                value = np.logaddexp(value, previous[s-1])
            if s >= 2 and c != 67 and c != extended[s-2]:
                value = np.logaddexp(value, previous[s-2])
            current[s] = value + logp[c, t]
        previous = current
    return float(np.logaddexp(previous[-1], previous[-2])) if target else float(previous[0])


def count(rows, threshold):
    accepted = [r for r in rows if r['score'] is not None and r['score'] >= threshold]
    correct = sum(r['code'] == r['label'] for r in accepted)
    return dict(correct=correct, wrong=len(accepted)-correct, rejected=len(rows)-len(accepted), total=len(rows))


def main():
    frozen = read_json(OUT/'frozen.json')
    assert all(sha(OUT/name) == digest for name, digest in frozen['artifacts'].items())
    config = read_json(OUT/'config.json')
    assert all(sha(ROOT/name) == digest for name, digest in config['input_hashes'].items())
    result = read_json(OUT/'results.json')
    gates = read_json(OUT/'gates.json')
    manifest = read_json(ROOT/'tmp/blue-plate-char-segment/experiment/dev-manifest.json')['records']
    train_identities = {r['identity'] for r in manifest if r['split'] == 'train'}
    tune_identities = {r['identity'] for r in manifest if r['split'] == 'tune'}
    assert len(train_identities) == 228 and len(tune_identities) == 76
    assert not train_identities & tune_identities
    checks = {}
    for variant in config['variants']:
        logits = np.load(OUT/f'{variant}-logits.npz')['logits']
        rows = read_json(OUT/f'{variant}-roi-records.json')
        differences = []
        for x, row in zip(logits, rows):
            differences.append(abs(ctc_dp(x, row['decoded_ids'])-row['sequence_log_probability']))
        assert len(rows) == 307 and max(differences) < 1e-11
        for mode in ('ocr_only', 'combined'):
            selected = read_json(OUT/f'{variant}-{mode}-selected.json')
            for r in selected:
                candidates = [p for p in rows if p['sample_index'] == r['sample_index'] and p['legal']
                              and (mode == 'ocr_only' or gates[p['roi_index']]['combined_pass'])]
                candidates.sort(key=lambda p: (-p['score'], p['roi_index']))
                assert r['roi_index'] == (candidates[0]['roi_index'] if candidates else None)
            for key, budget in [('max_wrong3', 3), ('zero_wrong', 0)]:
                actual = result[variant][mode][key]
                assert count(selected, actual['threshold']) == actual['development']
                assert count([r for r in selected if r['split'] == 'tune'], actual['threshold']) == actual['tune']
                grid = {0., 1.000001} | {r['score'] for r in selected if r['score'] is not None}
                feasible = [(t, count(selected, t)) for t in grid]
                optimum = max((m['correct'], -m['wrong'], -t) for t, m in feasible if m['wrong'] <= budget)
                assert optimum == (actual['development']['correct'], -actual['development']['wrong'], -actual['threshold'])
        checks[variant] = dict(ctc_max_abs_logp_error=max(differences), candidates_checked=len(rows),
                               repeated_targets_checked=sum(any(a == b for a, b in zip(r['decoded_ids'], r['decoded_ids'][1:])) for r in rows),
                               independent_selection_and_thresholds_match=True)
    a = np.load(OUT/'original_cv2_linear-inputs.npz')['bgr'].astype(np.int16)
    b = np.load(OUT/'q8_bgr-inputs.npz')['bgr'].astype(np.int16)
    ar = read_json(OUT/'original_cv2_linear-roi-records.json')
    br = read_json(OUT/'q8_bgr-roi-records.json')
    checks['resize_difference'] = dict(max_abs=int(np.abs(a-b).max()), mean_abs=float(np.abs(a-b).mean()),
        changed_fraction=float(np.mean(a != b)), changed_greedy_rois=sum(x['code'] != y['code'] for x, y in zip(ar, br)))
    old_path = ROOT/'tmp/blue-plate-review/mature-research/ctc-comparison.json'
    old = read_json(old_path)['methods']['greedy_sequence_probability']
    split_by_path = {r['path']: r['split'] for r in manifest}
    old_rows = []
    for r in old['rows']:
        if r['path'] in split_by_path:
            assert r['split'] == 'development'
            p = r['selected']
            old_rows.append(dict(split=split_by_path[r['path']], label=r['label'], code=p['text'] if p else None,
                                 score=p['score'] if p else None))
    assert len(old_rows) == 304
    checks['previous_lpr_old_roi_frozen_threshold'] = dict(source=str(old_path.relative_to(ROOT)), source_sha256=sha(old_path),
        threshold=old['threshold'], development=count(old_rows, old['threshold']),
        tune=count([r for r in old_rows if r['split'] == 'tune'], old['threshold']))
    checks['frozen_artifacts_unchanged'] = all(sha(OUT/name) == digest for name, digest in frozen['artifacts'].items())
    write_json(OUT/'verification.json', checks)
    print(checks)


if __name__ == '__main__':
    main()
