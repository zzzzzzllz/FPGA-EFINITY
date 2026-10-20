"""Freeze and evaluate exactly one train207-calibrated tap2 fork candidate."""
from collections import Counter
import math
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from experiment import ROOT, read_json, write_json, sha
from fixed_lprnet import FixedLPRNet, STRICT_THRESHOLD
from pretrained_new_rois import decode
from quantize_lprnet import score_rows
from integer_lprnet import FloatTrace, graph, dequantize
from integer_lprnet_fork import ForkLPR, fork_parameters, FORK, TRUNK

OLD = ROOT/'tmp/blue-plate-char-segment/quantization-w8a8'
OUT = ROOT/'tmp/blue-plate-char-segment/quantization-tap2-fork'
DEV = ROOT/'tmp/blue-plate-char-segment/pretrained-new-rois'


def resource_plan():
    coarse, fine = 256*18*44, 64*18*44
    assert coarse+fine <= 262144
    block = 12*(256+64)
    assert block <= 4096 and 320 <= 512
    arena = 7014592+576
    assert arena <= 8*1024*1024
    # Enumerate output-block writes and both DDR intervals, including final block.
    covered = np.zeros((792, 320), np.uint8)
    for start in range(0, 792, 12):
        covered[start:start+12] += 1
    assert np.all(covered == 1)
    return dict(ram_banks=51, mac_dsps=8, parameter_rows=320, parameter_capacity=512,
        parameter_extra_payload_bytes=320, parameter_extra_reserved_bytes=576,
        output_block_bytes=block, output_block_capacity=4096, spatial_block_size=12, spatial_blocks=66,
        coarse_ddr_interval=[0, coarse], trunk_ddr_interval=[coarse, coarse+fine], slot_capacity=262144,
        input_live_bytes=fine, fork_live_bytes=coarse+2*fine, extra_requantizations=fine,
        extra_weight_reads_bytes=(66-50)*16384, extra_activation_writes_bytes=fine,
        arena_bytes=arena, arena_capacity=8*1024*1024, extra_ram_banks=0, extra_mac_dsps=0,
        extra_full_int32_feature_buffers=0, extra_mac_operations=0,
        lifecycle='keep both tap2 outputs until context consumed and trunk maxpool reads complete; single outstanding DMA',
        block_coverage_verified=True, hardware_map_pass=False)


def state(row):
    if row['score'] is None or row['score'] < STRICT_THRESHOLD:
        return 'rejected'
    return 'correct' if row['code'] == row['label'] else 'wrong'


def main():
    if OUT.exists():
        raise FileExistsError(f'Preserve candidate: {OUT}')
    OUT.mkdir()
    started = time.monotonic()
    torch.set_num_threads(4)
    original_freeze = read_json(OLD/'delivery-freeze.json')['artifacts']
    assert all(sha(ROOT/n) == h for n, h in original_freeze.items())
    source_files = [Path(__file__), Path(__file__).with_name('integer_lprnet_fork.py'),
        ROOT/'docs/validation/blue-plate/char-segment/quantization-fork-plan.md',
        ROOT/'docs/validation/blue-plate/whole-plate-budget/full-lprnet-sharing.md',
        ROOT/'docs/validation/blue-plate/whole-plate-budget/color-cnn-sharing.md']
    sources = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in source_files}
    sources.update(read_json(OLD/'protocol.json')['source_hashes'])
    assert all(sha(ROOT/n) == h for n, h in sources.items())
    train = read_json(OLD/'parameter-freeze.json')['calibration_roi_indices']
    manifest = read_json(ROOT/'tmp/blue-plate-char-segment/experiment/dev-manifest.json')['records']
    assert len(train) == len(set(train)) == 207 and all(manifest[i]['split'] == 'train' for i in train)
    images = np.load(DEV/'q8_bgr-inputs.npz')['bgr']
    assert len(images) == len(manifest) == 307
    gates = read_json(DEV/'gates.json')
    write_json(OUT/'protocol.json', dict(sources=sources, original_delivery_sha=sha(OLD/'delivery-freeze.json'),
        calibration_roi_indices=train, threshold=STRICT_THRESHOLD, candidates=1, optimizer_steps=0,
        validation_image_reads=0, heldout_image_reads=0, resource_plan=resource_plan()))
    runner = FixedLPRNet()
    net = runner.net
    state_before = {k: v.clone() for k, v in net.state_dict().items()}
    observer = FloatTrace(net, graph(net))
    lo, hi = 0., 0.
    calibration_records = []
    with torch.inference_mode():
        for count, i in enumerate(train):
            fp = observer(images[i])
            selected = fp[FORK][:, ::4]
            lo, hi = min(lo, float(selected.min())), max(hi, float(selected.max()))
            assert torch.equal(F.max_pool2d(selected, 3, (1, 2)), fp['backbone.14'])
            calibration_records.append(dict(roi_index=i, minimum=float(selected.min()), maximum=float(selected.max())))
            if count % 50 == 0:
                print('fork calibration', count+1, '/207', flush=True)
        original_config = read_json(OLD/'integer-config.json')
        original_arrays = dict(np.load(OLD/'integer-parameters.npz'))
        config, arrays = fork_parameters(net, original_config, original_arrays, (lo, hi))
        write_json(OUT/'calibration.json', dict(range=[lo, hi], records=calibration_records, fp32_pool_checks=207))
        write_json(OUT/'integer-config.json', config)
        np.savez_compressed(OUT/'integer-parameters.npz', **arrays)
        parameter_hashes = {n: sha(OUT/n) for n in ['calibration.json', 'integer-config.json', 'integer-parameters.npz']}
        write_json(OUT/'parameter-freeze.json', dict(artifacts=parameter_hashes, before_evaluation=True))
        integer = ForkLPR(config, arrays)
        frozen_fp = np.load(DEV/'q8_bgr-logits.npz')['logits']
        fp_predictions = read_json(DEV/'q8_bgr-roi-records.json')
        old_predictions = read_json(OLD/'roi-predictions.json')
        predictions, logits_rows, roi_rows, errors = [], [], [], {}
        for i, image in enumerate(images):
            fp = observer(image)
            assert np.array_equal(fp['logits'][0].numpy(), frozen_fp[i])
            fp[TRUNK] = fp[FORK][:, ::4]
            assert torch.equal(F.max_pool2d(fp[TRUNK], 3, (1, 2)), fp['backbone.14'])
            logits, trace, statistics, vectors = integer(image, capture_vectors=i == 0)
            if i == 0:
                np.savez_compressed(OUT/'fork-vectors.npz', **vectors)
            roi_errors = {}
            for name, item in trace.items():
                actual, reference = dequantize(item), fp[name].double()
                assert actual.shape == reference.shape
                delta = actual-reference
                se, sr = float(delta.square().sum()), float(reference.square().sum())
                record = errors.setdefault(name, dict(squared_error=0., squared_reference=0., absolute_error=0., elements=0, max_abs=0., integer_min=int(item[0].min()), integer_max=int(item[0].max())))
                record['squared_error'] += se
                record['squared_reference'] += sr
                record['absolute_error'] += float(delta.abs().sum())
                record['elements'] += actual.numel()
                record['max_abs'] = max(record['max_abs'], float(delta.abs().max()))
                record['integer_min'] = min(record['integer_min'], int(item[0].min()))
                record['integer_max'] = max(record['integer_max'], int(item[0].max()))
                roi_errors[name] = dict(relative_rmse=math.sqrt(se/sr) if sr else None, max_abs=float(delta.abs().max()))
            prediction = dict(roi_index=i, **decode(logits[0].double()*config['logit_scale'], runner.chars))
            predictions.append(prediction)
            logits_rows.append(logits[0].numpy())
            roi_rows.append(dict(roi_index=i, split=manifest[i]['split'], errors=roi_errors, arithmetic=statistics))
            if i % 50 == 0:
                print('fork development', i+1, '/307', flush=True)
        for record in errors.values():
            record['relative_rmse'] = math.sqrt(record['squared_error']/record['squared_reference']) if record['squared_reference'] else None
            record['mean_abs'] = record['absolute_error']/record['elements']
        report, selection = score_rows(predictions, manifest, gates)
        fp_report, fp_selection = score_rows(fp_predictions, manifest, gates)
        old_report, old_selection = score_rows(old_predictions, manifest, gates)
        changes = {}
        for label, baseline in [('fp32', fp_selection), ('first_integer', old_selection)]:
            changes[label] = {}
            for mode, rows in selection.items():
                old = {r['sample_index']: r for r in baseline[mode]}
                changes[label][mode] = dict(transitions=dict(Counter(state(old[r['sample_index']])+' -> '+state(r) for r in rows)),
                    rows=[dict(before=old[r['sample_index']], after=r) for r in rows if state(old[r['sample_index']]) != state(r)])
        write_json(OUT/'roi-predictions.json', predictions)
        write_json(OUT/'selected.json', selection)
        write_json(OUT/'acceptance-changes.json', changes)
        write_json(OUT/'roi-layer-errors.json', roi_rows)
        write_json(OUT/'layer-summary.json', errors)
        np.savez_compressed(OUT/'integer-logits.npz', logits=np.stack(logits_rows))
        assert all(torch.equal(v, net.state_dict()[k]) for k, v in state_before.items())
        assert all(sha(ROOT/n) == h for n, h in original_freeze.items())
        assert all(sha(ROOT/n) == h for n, h in sources.items())
        assert all(sha(OUT/n) == h for n, h in parameter_hashes.items())
        result = dict(fp32=fp_report, first_integer=old_report, fork_integer_with_float_ctc=report,
            greedy_changed_vs_fp32=sum(p['code'] != q['code'] for p, q in zip(predictions, fp_predictions)),
            greedy_changed_vs_first_integer=sum(p['code'] != q['code'] for p, q in zip(predictions, old_predictions)),
            fp32_pool_selection_checks=514, prior_fusion_max_abs=4.57763671875e-5,
            trunk_quantization=config['fork']['output'], calibration_range=[lo, hi],
            original_delivery_unchanged=True, parameters_unchanged=True, model_state_unchanged=True,
            optimizer_steps=0, validation_image_reads=0, heldout_image_reads=0, elapsed_seconds=time.monotonic()-started)
        write_json(OUT/'results.json', result)
        write_json(OUT/'frozen.json', dict(artifacts={p.name: sha(p) for p in OUT.iterdir() if p.is_file()}))
        observer.close()
        print(result, flush=True)


if __name__ == '__main__':
    main()
