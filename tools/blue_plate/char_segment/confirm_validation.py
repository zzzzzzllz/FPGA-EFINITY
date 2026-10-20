"""One fixed-threshold confirmation on the existing 84 validation/calibration images."""
from collections import Counter
from pathlib import Path
import time

import numpy as np
import torch

from experiment import ROOT, OUT as INPUT, DETECTOR, SAMPLES, prepare, read_json, write_json, sha, array_sha
from fixed_lprnet import FixedLPRNet, STRICT_THRESHOLD, COMPARISON_THRESHOLD
from verify_pretrained_new_rois import ctc_dp

OUT = ROOT/'tmp/blue-plate-char-segment/pretrained-validation'


def outcome(code, label):
    return 'rejected' if code is None else 'correct' if code == label else 'wrong'


def counts(rows):
    counter = Counter(r['outcome'] for r in rows)
    return dict(total=len(rows), **{k: counter[k] for k in ('correct', 'wrong', 'rejected')})


def main():
    if OUT.exists():
        raise FileExistsError(f'Preserve existing confirmation: {OUT}')
    started = time.monotonic()
    torch.set_num_threads(4)
    frozen_dev = ROOT/'tmp/blue-plate-char-segment/pretrained-new-rois'
    freeze = read_json(frozen_dev/'delivery-freeze.json')['artifacts']
    assert all(sha(ROOT/name) == digest for name, digest in freeze.items())
    dev_result = read_json(frozen_dev/'results.json')['q8_bgr']
    for mode in ('ocr_only', 'combined'):
        assert STRICT_THRESHOLD == dev_result[mode]['zero_wrong']['threshold']
        assert COMPARISON_THRESHOLD == dev_result[mode]['max_wrong3']['threshold']
    samples = read_json(SAMPLES)
    validation = {i: s for i, s in enumerate(samples) if s['split'] == 'validation'}
    assert len(validation) == 84
    assert len({s['label'] for s in validation.values()}) == 84
    assert not {s['label'] for s in validation.values()} & {s['label'] for s in samples if s['split'] != 'validation'}
    source_files = [Path(__file__), Path(__file__).with_name('fixed_lprnet.py'),
        Path(__file__).with_name('pretrained_new_rois.py'), Path(__file__).with_name('experiment.py'),
        ROOT/'tools/blue_plate/geometry_sampler.py', ROOT/'tools/blue_plate/compare_hyperlpr.py',
        ROOT/'tools/blue_plate/baseline.py', SAMPLES, DETECTOR/'comparison-records.json',
        DETECTOR/'color-candidate-confirmation/records.json',
        ROOT/'tmp/blue-plate-normal-g1/full-dual-local-geometry/results.json', frozen_dev/'delivery-freeze.json']
    source_hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in source_files}
    OUT.mkdir()
    write_json(OUT/'protocol.json', dict(thresholds=dict(strict=STRICT_THRESHOLD, comparison=COMPARISON_THRESHOLD),
        thresholds_frozen_before_validation=True, threshold_fitting=False, validation_sample_indices=list(validation),
        source_hashes=source_hashes, pipeline='frozen detector320 integer corners -> integer Q32/Q5 224x64 BGR -> Q8 94x24 BGR',
        primary='strict', comparison_only='comparison', batch_size=1, classes=68, blank=67,
        pretrained_identity_overlap='unknown', heldout_image_reads=0, training_steps=0))
    if (INPUT/'val-inputs.npz').exists() or (INPUT/'val-manifest.json').exists():
        raise FileExistsError('Unexpected pre-existing validation cache; inspect provenance before reuse')
    prepare('validation')
    manifest = read_json(INPUT/'val-manifest.json')['records']
    images = np.load(INPUT/'val-inputs.npz')['bgr']
    assert len(manifest) == len(images)
    assert {r['sample_index'] for r in manifest} == set(validation)
    gates_by_sample = {r['sample_index']: r for r in read_json(DETECTOR/'color-candidate-confirmation/records.json')
                       if r['kind'] == 'positive' and r['split'] == 'validation'}
    old_by_path = {r['path']: r for r in read_json(ROOT/'tmp/blue-plate-normal-g1/full-dual-local-geometry/results.json')
                   if r['mode'] == 'automatic' and r['split'] == 'validation'}
    assert len(gates_by_sample) == len(old_by_path) == 84
    net = FixedLPRNet()
    state_before = {k: v.clone() for k, v in net.net.state_dict().items()}
    # Confirm the reusable entry against previously frozen development logits before validation inference.
    dev_images = np.load(INPUT/'dev-inputs.npz')['bgr']
    dev_logits = np.load(frozen_dev/'q8_bgr-logits.npz')['logits']
    entry_checks = []
    for i in (0, 1, 13, 306):
        actual = net(dev_images[i])
        assert np.array_equal(actual['logits'], dev_logits[i])
        entry_checks.append(dict(roi_index=i, logits_exact=True))
    roi_records, logits_all, dp_errors = [], [], []
    for i, (r, image) in enumerate(zip(manifest, images)):
        assert r['roi_index'] == i and r['original_split'] == r['split'] == 'validation'
        s = validation[r['sample_index']]
        assert s['path'] == r['path'] and s['sha256'] == r['source_sha256'] and s['label'] == r['source_transcript']
        assert array_sha(image) == r['roi_bgr_sha256']
        frame = gates_by_sample[r['sample_index']]
        assert frame['source'] == r['path']
        gate = frame['result']['outputs'][r['candidate_index']]
        assert gate['points'] == r['points'] == r['teacher_cached']['points']
        assert gate['box'] == r['teacher_cached']['box']
        assert gate['code'] == r['teacher_cached']['code']
        assert gate['blue_evidence_pass'] == (gate['blue_count'] > gate['yellow_count'])
        combined_pass = (gate['color_class'] == 0 and gate['blue_evidence_pass']
                         and gate['corner_margin'] >= 1 and gate['box_margin'] >= 1)
        result = net(image)
        logits = result.pop('logits')
        delta = abs(ctc_dp(logits, result['decoded_ids'])-result['sequence_log_probability'])
        assert delta < 1e-11
        dp_errors.append(delta)
        logits_all.append(logits)
        roi_records.append(dict(roi_index=i, sample_index=r['sample_index'], candidate_index=r['candidate_index'],
            path=r['path'], label=r['source_transcript'], points=r['points'], inverse_q32=r['inverse_q32'],
            roi_bgr_sha256=r['roi_bgr_sha256'], combined_pass=bool(combined_pass),
            gate={k: gate[k] for k in ('color_class', 'blue_count', 'yellow_count', 'corner_margin', 'box_margin')}, **result))
        if i % 20 == 0:
            print(f'Validation ROI {i+1}/{len(images)}', flush=True)
    write_json(OUT/'roi-records.json', roi_records)
    np.savez_compressed(OUT/'logits.npz', logits=np.stack(logits_all))
    frames = []
    for index, sample in validation.items():
        proposals = [r for r in roi_records if r['sample_index'] == index]
        methods = {}
        for mode in ('ocr_only', 'combined'):
            legal = [r for r in proposals if r['legal'] and (mode == 'ocr_only' or r['combined_pass'])]
            best = max(legal, key=lambda r: (r['score'], -r['roi_index'])) if legal else None
            for name, threshold in [('strict', STRICT_THRESHOLD), ('comparison', COMPARISON_THRESHOLD), ('raw_legal', 0.)]:
                code = best['code'] if best is not None and best['score'] >= threshold else None
                methods[f'{mode}_{name}'] = dict(code=code, outcome=outcome(code, sample['label']),
                    selected_roi_index=best['roi_index'] if best else None, score=best['score'] if best else None,
                    threshold=threshold)
        old = old_by_path[sample['path']]['result']
        accepted = old['status'] == 'scored' and len(old['scores']) == 7 and all(s['accepted'] for s in old['scores'])
        old_code = old['raw'] if accepted else None
        methods['old_backend'] = dict(code=old_code, outcome=outcome(old_code, sample['label']))
        teacher = gates_by_sample[index]['result']['candidate_selected']
        teacher_code = teacher['code'] if teacher else None
        methods['teacher_frozen_native_combined'] = dict(code=teacher_code, outcome=outcome(teacher_code, sample['label']))
        frames.append(dict(sample_index=index, path=sample['path'], label=sample['label'], split='validation', methods=methods))
    assert len(frames) == 84
    summary = {name: counts([r['methods'][name] for r in frames]) for name in frames[0]['methods']}
    assert all(torch.equal(state_before[k], v) for k, v in net.net.state_dict().items())
    assert all(sha(ROOT/name) == digest for name, digest in source_hashes.items())
    assert all(sha(ROOT/name) == digest for name, digest in freeze.items())
    write_json(OUT/'frame-records.json', frames)
    write_json(OUT/'results.json', dict(summary=summary, validation_images=84, validation_rois=len(manifest),
        training_steps=0, heldout_image_reads=0, threshold_fitting=False, model_state_unchanged=True,
        development_delivery_unchanged=True, entry_development_checks=entry_checks,
        independent_dp_max_abs_error=max(dp_errors), elapsed_seconds=time.monotonic()-started,
        cache_hashes={p.name: sha(p) for p in [INPUT/'val-inputs.npz', INPUT/'val-manifest.json']}))
    write_json(OUT/'frozen.json', dict(artifacts={p.name: sha(p) for p in OUT.iterdir() if p.is_file()}))
    print(summary, flush=True)


if __name__ == '__main__':
    main()
