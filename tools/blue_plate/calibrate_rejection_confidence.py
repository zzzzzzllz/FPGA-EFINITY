"""Development-only follow-up score aggregation; frozen validation evaluation.

This is exploratory after full-frame failure inspection, not pristine acceptance.
Compares a weakest-character gate with merely raising the existing mean gate.
"""
import hashlib
import json
from pathlib import Path

from compare_hyperlpr import ROOT, OUT


def main():
    source = OUT/'fullframe-rejection/records.json'
    out = OUT/'fullframe-confidence-followup'
    out.mkdir(exist_ok=False)
    protocol = dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        base_gate='grammar_color_p90_box_corners_inside',
        grids=dict(min_emission=[0, .5, .6, .7, .8, .9, .95, .99], mean=[0, .8, .9, .95, .98, .99]),
        selection='Development only: zero accepted edited frames; maximize positive correct; then lower threshold. Reject candidate if none qualifies.',
        provenance='Exploratory follow-up after inspecting earlier development and validation failure images. Not G1 or fresh independent validation.',
        labels='No edited input receives an original or teacher transcript training label.', heldout_images_read=0)
    (out/'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf8')
    rows = json.loads(source.read_text(encoding='utf8'))
    def score(p, method):
        return min(p['emission_scores']) if method == 'min_emission' else p['confidence']
    def evaluate(split, method, threshold):
        result = {}
        for kind in sorted({r['kind'] for r in rows}):
            group = [r for r in rows if r['split'] == split and r['kind'] == kind]
            counts = dict(total=len(group), accepted=0, correct=0, wrong=0, reject=0)
            for row in group:
                accepted = [p for p in row['outputs'] if p.get(protocol['base_gate']) and score(p, method) >= threshold]
                best = max(accepted, key=lambda p:p['confidence'], default=None)
                counts['accepted'] += best is not None
                counts['reject'] += best is None
                if kind == 'positive' and best is not None:
                    counts['correct' if best['code'] == row['original_reference_text'] else 'wrong'] += 1
            result[kind] = counts
        return result
    report = dict(protocol=protocol, methods={})
    for method, grid in protocol['grids'].items():
        dev = [dict(threshold=t, metrics=evaluate('development', method, t)) for t in grid]
        eligible = [x for x in dev if all(m['accepted'] == 0 for k,m in x['metrics'].items() if k != 'positive')]
        chosen = max(eligible, key=lambda x:(x['metrics']['positive']['correct'], -x['threshold']), default=None)
        report['methods'][method] = dict(development_grid=dev, selected=chosen,
            validation=evaluate('validation', method, chosen['threshold']) if chosen else None)
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    for method, result in report['methods'].items():
        print(method, json.dumps(dict(selected=result['selected'], validation=result['validation']), ensure_ascii=False))


if __name__ == '__main__':
    main()
