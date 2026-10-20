"""388 positive frames: native/fixed crop color CNN only, frozen LPR scores.

Does not call the newly proposed structure rule or run validation calibration.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT, OUT, SOURCE, inspected_functions
from diagnose_color_evidence import color_evidence
from probe_hyperlpr_rejection import canvas720

DEST = OUT/'positive-color-cnn-comparison'
THRESHOLDS = dict(strict=0.9931710550839266, comparison=0.9386077887914179)


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def main():
    DEST.mkdir(exist_ok=False)
    cv2.setNumThreads(2)
    model = OUT/'litemodel_cls_96x_r1.onnx'
    assert sha(model) == 'fe123688d3bf08b9ef029fcd57f3ac4644ac2e5ef8b9e7a676aacd5fad152142'
    source_root = ROOT/'tmp/blue-plate-char-segment'
    sources = [Path(__file__), model, SOURCE/'inference/classification.py', SOURCE/'common/tools_process.py',
               OUT/'fullframe-rejection/records.json', OUT/'color-sampling-comparison/records.json',
               OUT/'structure-development-v1/candidate-freeze.json']
    for split in ['dev', 'val']:
        sources += [source_root/'experiment'/f'{split}-{suffix}' for suffix in ['inputs.npz', 'manifest.json']]
    sources += [source_root/'pretrained-new-rois/q8_bgr-roi-records.json', source_root/'pretrained-validation/roi-records.json']
    hashes = {str(p): sha(p) for p in sources}
    write(DEST/'protocol.json', dict(source_hashes=hashes, cnn_inference_rois=392, thresholds=THRESHOLDS,
        scope='Positive color sampling comparison only; frozen OCR scores and raw geometry; no structure evaluation or fitting.',
        heldout_read=0, structure_validation_run=False, classes_source='Original classifier, native resize96 vs cached Q32 224x64 resize96'))
    net = cv2.dnn.readNetFromONNX(str(model))
    encode = inspected_functions(SOURCE/'inference/classification.py', ['encode_images'])['encode_images']
    warp = inspected_functions(SOURCE/'common/tools_process.py', ['get_rotate_crop_image'])['get_rotate_crop_image']
    geometry = {r['sample_index']: r for r in read(OUT/'fullframe-rejection/records.json') if r['kind'] == 'positive'}
    groups = {}
    deltas, changes = [], []
    def color(image):
        net.setInput(encode(cv2.resize(image, (96, 96)))[None])
        scores = net.forward().reshape(-1)
        ev = color_evidence(image)
        return dict(color_class=int(scores.argmax()), scores=scores.tolist(),
                    blue_count=ev['counts']['blue_hs'], yellow_count=ev['counts']['yellow_hs'], hs_pass=ev['hs_blue_over_yellow'])
    for split, folder in [('dev', 'pretrained-new-rois'), ('val', 'pretrained-validation')]:
        images = np.load(source_root/'experiment'/f'{split}-inputs.npz')['bgr']
        manifest = read(source_root/'experiment'/f'{split}-manifest.json')['records']
        pred = read(source_root/folder/('q8_bgr-roi-records.json' if split == 'dev' else 'roi-records.json'))
        assert len(images) == len(manifest) == len(pred) == (307 if split == 'dev' else 85)
        last_path, frame = None, None
        for m, image, prediction in zip(manifest, images, pred):
            assert m['roi_index'] == prediction['roi_index']
            assert m['sample_index'] == prediction['sample_index'] and m['candidate_index'] == prediction['candidate_index']
            assert hashlib.sha256(image.tobytes()).hexdigest() == m['roi_bgr_sha256']
            if m['path'] != last_path:
                assert sha(ROOT/m['path']) == m['source_sha256']
                frame = canvas720(b.read_image(ROOT/m['path']))
                last_path = m['path']
            previous = geometry[m['sample_index']]['outputs'][m['candidate_index']]
            assert previous['points'] == m['points']
            native = color(warp(frame, np.array(m['points'])))
            fixed = color(image)
            assert native['color_class'] == previous['color_class']
            gate = previous['corner_margin'] >= 1 and previous['box_margin'] >= 1
            p = dict(candidate_index=m['candidate_index'], points=m['points'], boundary_pass=bool(gate),
                     native=native, fixed=fixed, code=prediction['code'], legal=prediction['legal'], score=prediction['score'],
                     roi_bgr_sha256=m['roi_bgr_sha256'])
            row = groups.setdefault(m['sample_index'], dict(sample_index=m['sample_index'], split=m['original_split'],
                path=m['path'], label=m['source_transcript'], outputs=[]))
            row['outputs'].append(p)
            deltas.append(np.abs(np.array(native['scores'])-np.array(fixed['scores'])))
            if native['color_class'] != fixed['color_class'] or native['hs_pass'] != fixed['hs_pass']:
                changes.append(dict(sample_index=m['sample_index'], split=m['original_split'], candidate=p))
    rows = list(groups.values())
    for r in rows:
        selections = {}
        for name, threshold in THRESHOLDS.items():
            for cnn_mode in ['native', 'fixed']:
                for hs_mode in ['native', 'fixed']:
                    allowed = [p for p in r['outputs'] if p['boundary_pass'] and p[cnn_mode]['color_class'] == 0
                               and p[hs_mode]['hs_pass'] and p['legal'] and p['score'] >= threshold]
                    best = max(allowed, key=lambda p:(p['score'], -p['candidate_index']), default=None)
                    selections[f'{name}/{cnn_mode}_cnn_{hs_mode}_hs'] = None if best is None else dict(
                        code=best['code'], score=best['score'], candidate_index=best['candidate_index'])
        r['selections'] = selections
    summary = {}
    for split in ['development', 'validation']:
        group = [r for r in rows if r['split'] == split]
        summary[split] = {}
        for method in group[0]['selections']:
            outcomes = Counter('rejected' if r['selections'][method] is None else 'correct'
                if r['selections'][method]['code'] == r['label'] else 'wrong' for r in group)
            summary[split][method] = dict(total=len(group), **{k: outcomes[k] for k in ['correct', 'wrong', 'rejected']})
    assert summary['development']['strict/native_cnn_native_hs'] == dict(total=304, correct=249, wrong=0, rejected=55)
    assert summary['validation']['strict/native_cnn_native_hs'] == dict(total=84, correct=68, wrong=0, rejected=16)
    assert hashes == {str(p): sha(p) for p in sources}
    selection_changes = [r for r in rows if any(r['selections'][f'{name}/{cnn}_cnn_{hs}_hs'] != r['selections'][f'{name}/native_cnn_native_hs']
        for name in THRESHOLDS for cnn in ['native', 'fixed'] for hs in ['native', 'fixed'])]
    report = dict(summary=summary, frames=len(rows), rois=sum(len(r['outputs']) for r in rows),
        learned_class_changes=sum(c['candidate']['native']['color_class'] != c['candidate']['fixed']['color_class'] for c in changes),
        hs_pass_changes=sum(c['candidate']['native']['hs_pass'] != c['candidate']['fixed']['hs_pass'] for c in changes),
        selected_frame_changes=len(selection_changes), color_probability_mean_absolute_delta=float(np.mean(deltas)),
        color_probability_max_absolute_delta=float(np.max(deltas)), frozen_sources_unchanged=True,
        structure_validation_run=False, heldout_read=0)
    write(DEST/'records.json', rows)
    write(DEST/'color-changes.json', changes)
    write(DEST/'selection-changes.json', selection_changes)
    write(DEST/'report.json', report)
    write(DEST/'artifacts.json', {p.name: sha(p) for p in DEST.iterdir() if p.is_file() and p.name != 'artifacts.json'})
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
