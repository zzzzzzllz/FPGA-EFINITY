"""Frozen LPRNet diagnostic; new OCR decisions, independently visible gates."""
from collections import Counter
from pathlib import Path
import sys

import cv2
import numpy as np
import torch

from prepare_lpr_rejection import DEST, ROOT, sha, write

sys.path.insert(0, str(ROOT/'tools/blue_plate/char_segment'))
from fixed_lprnet import FixedLPRNet, STRICT_THRESHOLD, COMPARISON_THRESHOLD
from verify_pretrained_new_rois import ctc_dp
from experiment import read_json


def choose(outputs, threshold, color_mode):
    eligible = []
    for p in outputs:
        if 'ocr' not in p or not p['ocr']['legal'] or p['ocr']['score'] < threshold:
            continue
        if color_mode != 'ocr_only':
            cnn_mode, hs_mode = color_mode.split('_cnn_')
            if p['boundary_pass'] is False or p[cnn_mode+'_color']['color_class'] != 0 or not p[hs_mode+'_color']['hs_pass']:
                continue
        eligible.append(p)
    best = max(eligible, key=lambda p:(p['ocr']['score'], -p['candidate_index']), default=None)
    return None if best is None else dict(candidate_index=best['candidate_index'], roi_index=best['roi_index'],
                                        code=best['ocr']['code'], score=best['ocr']['score'])


def main():
    if (DEST/'inference-freeze.json').exists():
        raise FileExistsError('Preserve existing diagnostic inference')
    torch.set_num_threads(4)
    preparation = read_json(DEST/'preparation-summary.json')
    for name, digest in preparation['artifacts'].items():
        assert sha(DEST/name) == digest
    sources = [Path(__file__), DEST/'prepared-records.json', DEST/'prepared-rois.npz']
    sources += [ROOT/'tools/blue_plate/char_segment'/p for p in ['fixed_lprnet.py', 'pretrained_new_rois.py',
                'experiment.py', 'verify_pretrained_new_rois.py']]
    thresholds = dict(strict=STRICT_THRESHOLD, comparison=COMPARISON_THRESHOLD)
    modes = ['ocr_only', 'native_cnn_native', 'native_cnn_fixed', 'fixed_cnn_native', 'fixed_cnn_fixed']
    hashes = {str(p): sha(p) for p in sources}
    write(DEST/'inference-freeze.json', dict(source_hashes=hashes, thresholds=thresholds,
        modes=modes, primary='strict/fixed_cnn_fixed', fit_thresholds=False, training=False,
        old_hyper_ocr_used=False, selection='max legal7 CTC score, ties lowest candidate index; apply independent frame boundary, learned blue and HS gates',
        input='224x64 BGR -> fixed entry Q8 24x94, original 68 classes/blank67, batch1 CPU'))
    runner = FixedLPRNet()
    state = {k: v.clone() for k, v in runner.net.state_dict().items()}
    frames = read_json(DEST/'prepared-records.json')
    images = np.load(DEST/'prepared-rois.npz')['bgr']
    results, logits_all, errors = [], [], []
    for i, image in enumerate(images):
        result = runner(image)
        logits = result.pop('logits')
        difference = abs(ctc_dp(logits, result['decoded_ids']) - result['sequence_log_probability'])
        assert difference < 1e-10
        errors.append(difference)
        results.append(result)
        logits_all.append(logits)
        if i % 200 == 0:
            print(f'LPR inference {i+1}/{len(images)}', flush=True)
    failure_rois = set()
    for frame in frames:
        for p in frame['outputs']:
            if 'roi_index' in p:
                assert p['bgr_sha256'] == __import__('hashlib').sha256(images[p['roi_index']].tobytes()).hexdigest()
                p['ocr'] = results[p['roi_index']]
        frame['selections'] = {f'{level}/{mode}': choose(frame['outputs'], threshold, mode)
                               for level, threshold in thresholds.items() for mode in modes}
        for key, selection in frame['selections'].items():
            if selection and not key.endswith('/ocr_only'):
                failure_rois.add(selection['roi_index'])
    summary = {}
    for input_kind, kind in sorted({(r['input_kind'], r['kind']) for r in frames}):
        group = [r for r in frames if r['input_kind'] == input_kind and r['kind'] == kind]
        summary[f'{input_kind}/{kind}'] = dict(inputs=len(group),
            accepted={key: sum(r['selections'][key] is not None for r in group) for key in group[0]['selections']})
    changes = []
    for frame in frames:
        for p in frame['outputs']:
            if 'ocr' not in p:
                continue
            if p['native_color']['color_class'] != p['fixed_color']['color_class'] or p['native_color']['hs_pass'] != p['fixed_color']['hs_pass']:
                changes.append(dict(id=frame['id'], input_kind=frame['input_kind'], kind=frame['kind'], candidate=p))
    assert all(torch.equal(v, state[k]) for k, v in runner.net.state_dict().items())
    assert hashes == {str(p): sha(p) for p in sources}
    write(DEST/'records.json', frames)
    write(DEST/'color-changes.json', changes)
    failures = [r for r in frames if any(v is not None for k, v in r['selections'].items() if not k.endswith('/ocr_only'))]
    write(DEST/'accepted-diagnostics.json', failures)
    np.savez_compressed(DEST/'logits.npz', logits=np.stack(logits_all))
    for i in sorted(failure_rois):
        cv2.imwrite(str(DEST/f'accepted-roi-{i}.png'), images[i])
    report = dict(summary=summary, inputs=len(frames), rois=len(images), thresholds=thresholds,
        independent_ctc_max_log_error=max(errors), model_state_unchanged=True, sources_unchanged=True,
        learned_class_changes=sum(r['candidate']['native_color']['color_class'] != r['candidate']['fixed_color']['color_class'] for r in changes),
        hs_pass_changes=sum(r['candidate']['native_color']['hs_pass'] != r['candidate']['fixed_color']['hs_pass'] for r in changes),
        detector_statuses=dict(Counter(r['detector_status'] for r in frames)),
        primary_accepted=sum(r['selections']['strict/fixed_cnn_fixed'] is not None for r in frames),
        accepted_combined_any_mode=len(failures), heldout_read=0, threshold_fit=False)
    write(DEST/'report.json', report)
    write(DEST/'inference-artifacts.json', {p.name: sha(p) for p in sorted(DEST.iterdir()) if p.is_file() and p.name != 'inference-artifacts.json'})
    print(report, flush=True)


if __name__ == '__main__':
    main()
