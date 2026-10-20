"""Verify frozen decisions and preserve representative strict-gate failures."""
import hashlib
import json

import cv2
import numpy as np

import baseline as b
from prepare_lpr_rejection import DEST, ROOT, OUT, SOURCE, sha, write, inspected_functions
from probe_hyperlpr_fullframe import variants
from probe_hyperlpr_rejection import canvas720


def main():
    frozen = json.loads((DEST/'inference-artifacts.json').read_text(encoding='utf8'))
    assert all(sha(DEST/name) == digest for name, digest in frozen.items())
    rows = json.loads((DEST/'records.json').read_text(encoding='utf8'))
    thresholds = json.loads((DEST/'inference-freeze.json').read_text())['thresholds']
    checked = 0
    for r in rows:
        for key, selection in r['selections'].items():
            level, mode = key.split('/')
            candidates = []
            for p in r['outputs']:
                if 'ocr' not in p or not p['ocr']['legal']:
                    continue
                if mode != 'ocr_only':
                    cnn, hs = mode.split('_cnn_')
                    if p['boundary_pass'] is False or p[cnn+'_color']['color_class'] != 0 or not p[hs+'_color']['hs_pass']:
                        continue
                candidates.append(p)
            candidates.sort(key=lambda p: (-p['ocr']['score'], p['candidate_index']))
            best = candidates[0] if candidates and candidates[0]['ocr']['score'] >= thresholds[level] else None
            assert (selection['roi_index'] if selection else None) == (best['roi_index'] if best else None)
            checked += 1
        for level in thresholds:
            base = r['selections'][level+'/native_cnn_native']
            for mode in ['native_cnn_fixed', 'fixed_cnn_native', 'fixed_cnn_fixed']:
                assert r['selections'][level+'/'+mode] == base
    originals = json.loads((OUT/'comparison-records.json').read_text(encoding='utf8'))
    originals = {r['sample_index']: r for r in originals}
    failures = []
    for r in rows:
        selection = r['selections']['strict/fixed_cnn_fixed']
        if selection is None:
            continue
        p = next(p for p in r['outputs'] if p.get('roi_index') == selection['roi_index'])
        original_text = originals[r['sample_index']]['label'] if 'sample_index' in r else None
        failures.append(dict(id=r['id'], sample_index=r.get('sample_index'), split=r['split'], path=r['path'], kind=r['kind'],
            original_unoccluded_text_evaluation_only=original_text, new_code=selection['code'], score=selection['score'],
            same_as_unoccluded_text=selection['code'] == original_text, roi_index=selection['roi_index'],
            corner_margin=p.get('corner_margin'), box_margin=p.get('box_margin'), fixed_color=p['fixed_color'],
            source_frame_sha256=r['frame_pixels_sha256'], roi_sha256=p['bgr_sha256'],
            intervention=r.get('intervention'), training_transcript=None))
    failures.sort(key=lambda r: -r['score'])
    write(DEST/'strict-failures.json', failures)
    selected = failures[:4] + [failures[-1], next(r for r in failures if r['split'] == 'validation')]
    selected = {r['id']: r for r in selected}
    warp = inspected_functions(SOURCE/'common/tools_process.py', ['get_rotate_crop_image'])['get_rotate_crop_image']
    examples = []
    for r in selected.values():
        original = originals[r['sample_index']]
        frame = canvas720(b.read_image(ROOT/original['path']))
        anchor = max(original['detector320'], key=lambda p:p['detector_confidence'])
        image = next(im for kind, im, _ in variants(frame, np.array(anchor['points']), warp) if kind == r['kind'])
        assert hashlib.sha256(image.tobytes()).hexdigest() == r['source_frame_sha256']
        path = DEST/f'failure-frame-{r["sample_index"]}.png'
        assert cv2.imwrite(str(path), image)
        examples.append(dict(id=r['id'], path=str(path), sha256=sha(path)))
    probabilities = [(p['native_color']['scores'], p['fixed_color']['scores']) for r in rows for p in r['outputs'] if 'ocr' in p]
    delta = np.abs(np.array([a for a, _ in probabilities])-np.array([b for _, b in probabilities]))
    report = dict(frozen_inference_artifacts_match=True, independently_selected_outputs=checked,
                  all_four_color_gate_combinations_select_identically=True,
                  color_score_mean_absolute_difference=float(delta.mean()), color_score_max_absolute_difference=float(delta.max()),
                  strict_failure_original_text_matches=sum(r['same_as_unoccluded_text'] for r in failures),
                  strict_failure_count=len(failures), source_frame_reconstructions=examples)
    write(DEST/'verification.json', report)
    print(report)


if __name__ == '__main__':
    main()
