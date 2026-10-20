"""One frozen tap2 candidate confirmation on the existing 84/85 validation cache."""
from collections import Counter
from pathlib import Path
import time

import numpy as np
import torch

from experiment import ROOT, read_json, write_json, sha, array_sha, resize_q8
from fixed_lprnet import FixedLPRNet, STRICT_THRESHOLD
from integer_lprnet_fork import ForkLPR
from pretrained_new_rois import decode
from verify_pretrained_new_rois import ctc_dp

MODEL = ROOT/'tmp/blue-plate-char-segment/quantization-tap2-fork'
FP = ROOT/'tmp/blue-plate-char-segment/pretrained-validation'
INPUT = ROOT/'tmp/blue-plate-char-segment/experiment'
OUT = ROOT/'tmp/blue-plate-char-segment/quantization-fork-validation'


def main():
    if OUT.exists():
        raise FileExistsError(f'Preserve one confirmation: {OUT}')
    OUT.mkdir()
    started = time.monotonic()
    torch.set_num_threads(4)
    frozen = read_json(MODEL/'delivery-freeze.json')['artifacts']
    assert all(sha(ROOT/n) == h for n, h in frozen.items())
    fp_records = read_json(FP/'roi-records.json')
    fp_frames = read_json(FP/'frame-records.json')
    expected_cache = read_json(FP/'results.json')['cache_hashes']
    source_files = [Path(__file__), FP/'roi-records.json', FP/'frame-records.json', FP/'results.json',
                    Path(__file__).with_name('experiment.py'), Path(__file__).with_name('pretrained_new_rois.py'),
                    Path(__file__).with_name('verify_pretrained_new_rois.py')]
    sources = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in source_files}
    write_json(OUT/'protocol.json', dict(model_delivery_sha=sha(MODEL/'delivery-freeze.json'),
        sources=sources, expected_cache_hashes=expected_cache, threshold=STRICT_THRESHOLD,
        primary_gate='existing base color/HS/corner/box combined gate', structural_gate_used=False,
        validation_images=84, validation_rois=85, heldout_image_reads=0, optimizer_steps=0,
        scales_fitted=False, threshold_fitted=False, source_image_reads=0,
        scope='controlled clear complete unoccluded single ordinary blue plate; occlusion is deferred'))
    assert all(sha(INPUT/n) == h for n, h in expected_cache.items())
    manifest = read_json(INPUT/'val-manifest.json')['records']
    images = np.load(INPUT/'val-inputs.npz')['bgr']
    assert images.shape == (85, 64, 224, 3) and images.dtype == np.uint8
    assert len(manifest) == len(fp_records) == 85 and len(fp_frames) == 84
    assert {r['sample_index'] for r in manifest} == {r['sample_index'] for r in fp_frames}
    config = read_json(MODEL/'integer-config.json')
    arrays = dict(np.load(MODEL/'integer-parameters.npz'))
    integer = ForkLPR(config, arrays)
    chars = FixedLPRNet().chars
    predictions, all_logits, resized_images, errors = [], [], [], []
    with torch.inference_mode():
        for i, (record, prior, image) in enumerate(zip(manifest, fp_records, images)):
            assert record['roi_index'] == prior['roi_index'] == i
            assert record['sample_index'] == prior['sample_index'] and record['candidate_index'] == prior['candidate_index']
            assert record['split'] == record['original_split'] == 'validation'
            assert record['path'] == prior['path'] and record['source_transcript'] == prior['label']
            assert array_sha(image) == record['roi_bgr_sha256'] == prior['roi_bgr_sha256']
            assert record['points'] == prior['points']
            resized = resize_q8(image, 24, 94)
            logits, _, _, _ = integer(resized)
            floating = logits[0].double()*config['logit_scale']
            decoded = decode(floating, chars)
            delta = abs(ctc_dp(floating.numpy(), decoded['decoded_ids'])-decoded['sequence_log_probability'])
            assert delta < 1e-11
            errors.append(delta)
            predictions.append(dict(roi_index=i, sample_index=record['sample_index'], candidate_index=record['candidate_index'],
                path=record['path'], label=prior['label'], combined_pass=prior['combined_pass'], gate=prior['gate'], **decoded))
            all_logits.append(logits[0].numpy())
            resized_images.append(resized)
            if i % 20 == 0:
                print('Frozen fork validation', i+1, '/85', flush=True)
    frames, changes = [], []
    for prior in fp_frames:
        proposals = [r for r in predictions if r['sample_index'] == prior['sample_index']]
        methods = {}
        for mode in ('ocr_only', 'combined'):
            legal = [r for r in proposals if r['legal'] and (mode == 'ocr_only' or r['combined_pass'])]
            best = max(legal, key=lambda r: (r['score'], -r['roi_index'])) if legal else None
            code = best['code'] if best is not None and best['score'] >= STRICT_THRESHOLD else None
            outcome = 'rejected' if code is None else 'correct' if code == prior['label'] else 'wrong'
            methods[mode+'_strict'] = dict(code=code, outcome=outcome, selected_roi_index=best['roi_index'] if best else None,
                selected_greedy_code=best['code'] if best else None, score=best['score'] if best else None, threshold=STRICT_THRESHOLD)
            before = prior['methods'][mode+'_strict']
            if before['outcome'] != outcome or before['code'] != code:
                changes.append(dict(sample_index=prior['sample_index'], label=prior['label'], mode=mode, before=before,
                                    after=methods[mode+'_strict']))
        frames.append(dict(sample_index=prior['sample_index'], path=prior['path'], label=prior['label'], methods=methods))
    result = dict(summary={}, fp32_summary={}, transitions={}, correct_losses={}, correct_gains={}, new_wrong={},
                  threshold=STRICT_THRESHOLD, scales_fitted=False, threshold_fitted=False, optimizer_steps=0,
                  validation_images=84, validation_rois=85, heldout_image_reads=0, source_image_reads=0,
                  independent_dp_max_abs_error=max(errors), elapsed_seconds=time.monotonic()-started)
    for mode in ('ocr_only_strict', 'combined_strict'):
        c = Counter(r['methods'][mode]['outcome'] for r in frames)
        result['summary'][mode] = dict(total=84, **{k: c[k] for k in ('correct', 'wrong', 'rejected')})
        result['fp32_summary'][mode] = read_json(FP/'results.json')['summary'][mode]
        pairs = [(old['methods'][mode], new['methods'][mode]) for old, new in zip(fp_frames, frames)]
        result['transitions'][mode] = dict(Counter(a['outcome']+' -> '+b['outcome'] for a, b in pairs))
        result['correct_losses'][mode] = sum(a['outcome']=='correct' and b['outcome']!='correct' for a,b in pairs)
        result['correct_gains'][mode] = sum(a['outcome']!='correct' and b['outcome']=='correct' for a,b in pairs)
        result['new_wrong'][mode] = sum(a['outcome']!='wrong' and b['outcome']=='wrong' for a,b in pairs)
    assert all(sha(ROOT/n) == h for n, h in frozen.items())
    assert all(sha(ROOT/n) == h for n, h in sources.items())
    assert all(sha(INPUT/n) == h for n, h in expected_cache.items())
    assert all(np.array_equal(integer.parameters[k].numpy(), v) for k, v in arrays.items())
    result.update(frozen_candidate_unchanged=True, input_cache_unchanged=True, integer_parameters_unchanged=True)
    write_json(OUT/'roi-records.json', predictions)
    write_json(OUT/'frame-records.json', frames)
    write_json(OUT/'acceptance-changes.json', changes)
    np.savez_compressed(OUT/'integer-logits.npz', logits=np.stack(all_logits))
    np.savez_compressed(OUT/'q8-inputs.npz', bgr=np.stack(resized_images))
    write_json(OUT/'results.json', result)
    write_json(OUT/'frozen.json', dict(artifacts={p.name: sha(p) for p in OUT.iterdir() if p.is_file()}))
    print(result, flush=True)


if __name__ == '__main__':
    main()
