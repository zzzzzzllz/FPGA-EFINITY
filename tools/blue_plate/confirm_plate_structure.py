"""Authorized fixed global-only structure confirmation: 84 positives/252 edits.

No OCR inference, local alternative, parameter selection, or heldout access.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT, OUT, SOURCE, inspected_functions
from geometry_sampler import sample_integer
from probe_hyperlpr_fullframe import variants
from probe_hyperlpr_rejection import canvas720

DEST = OUT/'structure-calibration-confirmation'
THRESHOLD = 0.9931710550839266


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def main():
    candidate_path = OUT/'structure-development-v1/candidate-freeze.json'
    assert sha(candidate_path) == '7264ba12ad2b3f2f7fb205beff3dab223f5d2461f3c47a23e3f54365f9a86e79'
    candidate = read(candidate_path)
    assert candidate['threshold'] == THRESHOLD
    assert all(sha(Path(p)) == h for p, h in candidate['source_hashes'].items())
    assert all(sha(candidate_path.parent/p) == h for p, h in candidate['artifact_hashes'].items())
    dev_root = ROOT/'tmp/blue-plate-char-segment'
    sources = [Path(__file__), candidate_path, Path(b.__file__), dev_root/'experiment/val-inputs.npz',
        dev_root/'experiment/val-manifest.json', dev_root/'pretrained-validation/roi-records.json',
        dev_root/'pretrained-validation/frame-records.json', OUT/'lpr-rejection/records.json',
        OUT/'positive-color-cnn-comparison/records.json', OUT/'color-candidate-confirmation/records.json',
        OUT/'comparison-records.json']
    hashes = {str(p): sha(p) for p in sources}
    DEST.mkdir(exist_ok=False)
    write(DEST/'protocol-before-confirmation.json', dict(candidate_sha256=sha(candidate_path), source_hashes=hashes,
        threshold=THRESHOLD, rule='global_seven only; original baseline.segment global/projection-char len(chars)==7',
        scope='Authorized 84 calibration positives and their 252 original edited frames; not independent blind test.',
        choose_rules=False, fit_parameters=False, ocr_inference=False, heldout_read=0,
        color_modes=['native CNN + native HS', 'fixed CNN + fixed HS'],
        original_freeze=candidate))
    images = np.load(dev_root/'experiment/val-inputs.npz')['bgr']
    manifest = read(dev_root/'experiment/val-manifest.json')['records']
    preds = read(dev_root/'pretrained-validation/roi-records.json')
    previous_positive = {r['sample_index']: r for r in read(dev_root/'pretrained-validation/frame-records.json')}
    colors = {r['sample_index']: r for r in read(OUT/'positive-color-cnn-comparison/records.json') if r['split'] == 'validation'}
    teacher = {(r['sample_index'], r['kind']): r for r in read(OUT/'color-candidate-confirmation/records.json')}
    rows, positives = [], {}
    count = 0

    def inspect(image, identity, prediction, native_color, fixed_color, boundary):
        nonlocal count
        chars, mask, rects = b.segment(image, 'global', 'projection-char')
        count += 1
        result = dict(**identity, code=prediction['code'], legal=prediction['legal'], score=prediction['score'],
            global_seven=len(chars) == 7, measured_rects=[list(map(int, r)) for r in rects],
            mask_sha256=hashlib.sha256(mask.tobytes()).hexdigest(), roi_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
            native_color=native_color, fixed_color=fixed_color, boundary_pass=boundary)
        if prediction['legal'] and prediction['score'] >= THRESHOLD and not result['global_seven']:
            cv2.imwrite(str(DEST/f'{identity["id"]}-roi-{identity["candidate_index"]}.png'), image)
            cv2.imwrite(str(DEST/f'{identity["id"]}-roi-{identity["candidate_index"]}-mask.png'), mask*255)
        return result

    assert len(images) == len(manifest) == len(preds) == 85
    for m, image, pred in zip(manifest, images, preds):
        assert m['original_split'] == 'validation'
        assert m['roi_index'] == pred['roi_index'] and m['sample_index'] == pred['sample_index'] and m['candidate_index'] == pred['candidate_index']
        assert hashlib.sha256(image.tobytes()).hexdigest() == m['roi_bgr_sha256'] == pred['roi_bgr_sha256']
        old = previous_positive[m['sample_index']]
        assert old['label'] == m['source_transcript'] and old['path'] == m['path']
        c = next(c for c in colors[m['sample_index']]['outputs'] if c['candidate_index'] == m['candidate_index'])
        assert c['roi_bgr_sha256'] == m['roi_bgr_sha256'] and c['points'] == m['points']
        assert c['code'] == pred['code'] and c['score'] == pred['score']
        r = positives.setdefault(m['sample_index'], dict(id=f'{m["sample_index"]}-positive', sample_index=m['sample_index'],
            kind='positive', label=m['source_transcript'], path=m['path'], source_sha256=m['source_sha256'], outputs=[],
            old_backend=old['methods']['old_backend'], teacher=old['methods']['teacher_frozen_native_combined']))
        r['outputs'].append(inspect(image, dict(id=r['id'], candidate_index=m['candidate_index']), pred, c['native'], c['fixed'], c['boundary_pass']))
    assert len(positives) == 84
    rows.extend(positives.values())
    previous_negative = {r['id']: r for r in read(OUT/'lpr-rejection/records.json') if r['split'] == 'validation'}
    assert len(previous_negative) == 252
    warp = inspected_functions(SOURCE/'common/tools_process.py', ['get_rotate_crop_image'])['get_rotate_crop_image']
    for original in read(OUT/'comparison-records.json'):
        if original['split'] != 'validation':
            continue
        assert sha(ROOT/original['path']) == positives[original['sample_index']]['source_sha256']
        frame = canvas720(b.read_image(ROOT/original['path']))
        anchor = max(original['detector320'], key=lambda p:p['detector_confidence'])
        for kind, edited, _ in variants(frame, np.array(anchor['points']), warp):
            if kind == 'positive':
                continue
            old = previous_negative[f'{original["sample_index"]}-{kind}']
            assert hashlib.sha256(edited.tobytes()).hexdigest() == old['frame_pixels_sha256']
            teacher_row = teacher[(original['sample_index'], kind)]['result']['candidate_selected']
            r = dict(id=old['id'], sample_index=original['sample_index'], kind=kind, path=original['path'], outputs=[],
                teacher=dict(code=teacher_row['code'] if teacher_row else None), old_backend=None)
            for p in old['outputs']:
                if 'ocr' not in p:
                    continue
                fixed, _ = sample_integer(edited, np.array(p['points']), 32, integer_solver=True)
                assert hashlib.sha256(fixed.tobytes()).hexdigest() == p['bgr_sha256']
                r['outputs'].append(inspect(fixed, dict(id=r['id'], candidate_index=p['candidate_index']),
                    p['ocr'], p['native_color'], p['fixed_color'], p['boundary_pass']))
            rows.append(r)
    assert len(rows) == 336
    changes = []
    for r in rows:
        r['methods'] = {}
        for color_mode in ['native', 'fixed']:
            for with_structure in [False, True]:
                allowed = [p for p in r['outputs'] if p['legal'] and p['score'] >= THRESHOLD and p['boundary_pass']
                    and p[color_mode+'_color']['color_class'] == 0 and p[color_mode+'_color']['hs_pass']
                    and (not with_structure or p['global_seven'])]
                best = max(allowed, key=lambda p:(p['score'], -p['candidate_index']), default=None)
                code = best['code'] if best else None
                name = color_mode+('_global' if with_structure else '_base')
                r['methods'][name] = dict(code=code, candidate_index=best['candidate_index'] if best else None,
                    score=best['score'] if best else None,
                    outcome='rejected' if code is None else 'correct' if r['kind'] == 'positive' and code == r['label'] else 'wrong')
        if r['methods']['native_base'] != r['methods']['native_global']:
            changes.append(r)
        if r['kind'] == 'positive':
            assert r['methods']['native_base']['code'] == previous_positive[r['sample_index']]['methods']['combined_strict']['code']
        else:
            selected = previous_negative[r['id']]['selections']['strict/native_cnn_native']
            assert r['methods']['native_base']['code'] == (selected['code'] if selected else None)
    summary = {}
    for kind in sorted({r['kind'] for r in rows}):
        group = [r for r in rows if r['kind'] == kind]
        summary[kind] = {}
        for name in ['native_base', 'fixed_base', 'native_global', 'fixed_global', 'teacher', 'old_backend']:
            if name == 'old_backend' and kind != 'positive':
                summary[kind][name] = None
                continue
            values = [r['methods'][name] if name in r['methods'] else r[name] for r in group]
            counts = Counter('rejected' if v['code'] is None else 'correct' if kind == 'positive' and v['code'] == r['label'] else 'wrong'
                for r, v in zip(group, values))
            summary[kind][name] = dict(total=len(group), **{k: counts[k] for k in ['correct', 'wrong', 'rejected']})
    assert hashes == {str(p): sha(p) for p in sources}
    write(DEST/'records.json', rows)
    write(DEST/'changes.json', changes)
    report = dict(summary=summary, frames=len(rows), rois=count, structure_rule='global only',
        candidate_sha256=sha(candidate_path), sources_unchanged=True, threshold_fit=False, heldout_read=0,
        color_selected_changes=sum(r['methods']['native_global'] != r['methods']['fixed_global'] for r in rows),
        structure_changed_inputs=len(changes))
    write(DEST/'report.json', report)
    write(DEST/'artifacts.json', {p.name: sha(p) for p in DEST.iterdir() if p.is_file() and p.name != 'artifacts.json'})
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
