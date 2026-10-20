"""Summarize frozen development results without inference or parameter changes."""
from collections import Counter

from experiment import ROOT, read_json, write_json, sha
from fixed_lprnet import STRICT_THRESHOLD
from quantize_lprnet import score_rows, OUT, DEV, INPUT


def status(row):
    if row['score'] is None or row['score'] < STRICT_THRESHOLD:
        return 'rejected'
    return 'correct' if row['code'] == row['label'] else 'wrong'


def main():
    manifest = read_json(INPUT/'dev-manifest.json')['records']
    gates = read_json(DEV/'gates.json')
    _, baseline = score_rows(read_json(DEV/'q8_bgr-roi-records.json'), manifest, gates)
    selected = read_json(OUT/'selected.json')
    train = set(read_json(OUT/'parameter-freeze.json')['calibration_roi_indices'])
    arithmetic = {}
    for row in read_json(OUT/'roi-layer-errors.json'):
        for layer, values in row['arithmetic'].items():
            a = arithmetic.setdefault(layer, dict(saturated=0, elements=0, saturated_calibration=0,
                                                   saturated_other=0, saturated_rois=[]))
            a['saturated'] += values['saturated']
            a['elements'] += values['elements']
            a['saturated_calibration' if row['roi_index'] in train else 'saturated_other'] += values['saturated']
            if values['saturated']:
                a['saturated_rois'].append(row['roi_index'])
            for key, value in values.items():
                if key in ('saturated', 'elements'):
                    continue
                a[key+'_min'] = min(a.get(key+'_min', value), value)
                a[key+'_max'] = max(a.get(key+'_max', value), value)
    transitions, changes, wrong = {}, {}, {}
    for mode, rows in selected.items():
        old = {r['sample_index']: r for r in baseline[mode]}
        transitions[mode] = dict(Counter(status(old[r['sample_index']])+' -> '+status(r) for r in rows))
        changes[mode] = [dict(before=old[r['sample_index']], after=r) for r in rows
                         if status(old[r['sample_index']]) != status(r)]
        wrong[mode] = [r for r in rows if status(r) == 'wrong']
    # Check protected source/docs without reading any validation image/cache.
    prior = read_json(ROOT/'tmp/blue-plate-char-segment/pretrained-validation/delivery-freeze.json')['artifacts']
    protected = {name: sha(ROOT/name) == digest for name, digest in prior.items()
                 if name.startswith(('tools/', 'docs/'))}
    assert all(protected.values())
    result = dict(strict_threshold=STRICT_THRESHOLD, transitions=transitions, changed_acceptance=changes,
                  strict_wrong=wrong, arithmetic=arithmetic, prior_frozen_source_docs_unchanged=protected)
    write_json(OUT/'analysis.json', result)
    print(dict(transitions=transitions, strict_wrong=wrong, protected_files=len(protected)))


if __name__ == '__main__':
    main()
