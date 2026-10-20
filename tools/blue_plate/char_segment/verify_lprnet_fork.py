"""Independent fork arithmetic, DDR block lifetime and frozen-score checks."""
from fractions import Fraction

import numpy as np
import torch
from torch.nn import functional as F

from experiment import ROOT, read_json, write_json, sha
from fixed_lprnet import FixedLPRNet
from integer_lprnet import IntegerLPR, FloatTrace, graph
from integer_lprnet_fork import ForkLPR, FORK, TRUNK
from quantize_lprnet_fork import OLD, OUT, DEV, resource_plan
from quantize_lprnet import score_rows


def requant(values, multiplier, shift, zero):
    result = np.empty(values.shape, np.int8)
    for channel in range(values.shape[1]):
        m, d = int(multiplier[channel]), 1 << int(shift[channel])
        result[:, channel] = np.array([max(-128, min(127, round(Fraction(max(0, int(v))*m, d))+zero))
                                      for v in values[:, channel].flat], np.int8).reshape(values[:, channel].shape)
    return result


def main():
    torch.set_num_threads(4)
    frozen = read_json(OUT/'frozen.json')['artifacts']
    assert all(sha(OUT/n) == h for n, h in frozen.items())
    config, old_config = read_json(OUT/'integer-config.json'), read_json(OLD/'integer-config.json')
    arrays, old_arrays = dict(np.load(OUT/'integer-parameters.npz')), dict(np.load(OLD/'integer-parameters.npz'))
    vectors = np.load(OUT/'fork-vectors.npz')
    image = np.load(DEV/'q8_bgr-inputs.npz')['bgr'][0]
    logits, trace, _, replay_vectors = ForkLPR(config, arrays)(image, capture_vectors=True)
    _, old_trace, _, _ = IntegerLPR(old_config, old_arrays)(image)
    assert np.array_equal(logits[0].numpy(), np.load(OUT/'integer-logits.npz')['logits'][0])
    assert all(np.array_equal(vectors[k], v) for k, v in replay_vectors.items())
    # Compute all selected-channel int32 accumulators using NumPy int64, no torch integer MAC.
    x = vectors['input'].astype(np.int64).reshape(64, -1)
    w = old_arrays[FORK+'.weight'][::4].astype(np.int64).reshape(64, 64)
    b = old_arrays[FORK+'.bias'][::4].astype(np.int64)
    accum = (w@x+b[:, None]).reshape(1, 64, 18, 44)
    assert np.array_equal(accum, vectors['accumulator'])
    fine = requant(accum, arrays[TRUNK+'.multiplier'], arrays[TRUNK+'.shift'], config['fork']['output']['zero'])
    coarse = requant(accum, arrays[FORK+'.multiplier'][::4], arrays[FORK+'.shift'][::4], -128)
    assert np.array_equal(fine, vectors['trunk'])
    assert np.array_equal(coarse, vectors['context'][:, ::4])
    assert np.array_equal(vectors['context'], old_trace[FORK][0].numpy())
    for branch in range(3):
        for suffix in ('average', 'normalized'):
            name = f'context.{branch}.{suffix}'
            assert torch.equal(trace[name][0], old_trace[name][0])
    windows = np.lib.stride_tricks.sliding_window_view(fine, (3, 3), axis=(2, 3))
    pooled = windows[:, :, :, ::2].max(axis=(-1, -2))
    assert np.array_equal(pooled, vectors['pooled'])
    # Same per-channel monotonic quantizer commutes with spatial max, before any A8 narrowing.
    maxima = np.lib.stride_tricks.sliding_window_view(accum, (3, 3), axis=(2, 3))[:, :, :, ::2].max(axis=(-1, -2))
    assert np.array_equal(requant(maxima, arrays[TRUNK+'.multiplier'], arrays[TRUNK+'.shift'], -128), pooled)
    net = FixedLPRNet().net
    observer = FloatTrace(net, graph(net))
    fp = observer(image)
    assert torch.equal(F.max_pool2d(fp[FORK][:, ::4], 3, (1, 2)), fp['backbone.14'])
    observer.close()
    # Replay actual values through a 4KiB block and two disjoint regions of one 256KiB slot.
    hardware = resource_plan()
    memory = np.zeros((2, hardware['slot_capacity']), np.int8)
    valid = np.zeros(memory.shape, np.bool_)
    source_bytes = vectors['input'][0].transpose(1, 2, 0).ravel()
    memory[0, :len(source_bytes)] = source_bytes
    valid[0, :len(source_bytes)] = True
    slot, initialized = memory[1], valid[1]
    context_hwc = vectors['context'][0].transpose(1, 2, 0).reshape(792, 256)
    trunk_hwc = fine[0].transpose(1, 2, 0).reshape(792, 64)
    offset = hardware['trunk_ddr_interval'][0]
    block = np.zeros(4096, np.int8)
    writes = 0
    for start in range(0, 792, 12):
        block[:3072] = context_hwc[start:start+12].ravel()
        block[3072:3840] = trunk_hwc[start:start+12].ravel()
        for address, source in ((start*256, block[:3072]), (offset+start*64, block[3072:3840])):
            assert not initialized[address:address+len(source)].any()
            slot[address:address+len(source)] = source
            initialized[address:address+len(source)] = True
            writes += 1
    assert initialized[:253440].all() and not initialized[253440:].any()
    assert np.array_equal(memory[0, :len(source_bytes)], source_bytes)
    assert int(valid.sum()) == hardware['fork_live_bytes']
    valid[0] = False  # Last convolution read finished; the previous input slot is now reusable.
    assert np.array_equal(slot[:offset].reshape(18, 44, 256), context_hwc.reshape(18, 44, 256))
    # The context region is consumed before release; the trunk region remains valid during pool reads.
    initialized[:offset] = False
    assert initialized[offset:253440].all()
    reconstructed = slot[offset:253440].reshape(18, 44, 64).transpose(2, 0, 1)[None]
    assert np.array_equal(reconstructed, fine)
    assert np.array_equal(np.lib.stride_tricks.sliding_window_view(reconstructed, (3, 3), axis=(2, 3))[:, :, :, ::2].max(axis=(-1, -2)), pooled)
    pool_bytes = pooled[0].transpose(1, 2, 0).ravel()
    assert not valid[0, :len(pool_bytes)].any()
    memory[0, :len(pool_bytes)] = pool_bytes
    valid[0, :len(pool_bytes)] = True
    initialized[offset:253440] = False
    assert not initialized.any()
    assert int(valid.sum()) == 21504
    changed_arrays = [k for k in old_arrays if not np.array_equal(old_arrays[k], arrays[k])]
    assert set(changed_arrays) <= {'backbone.16.bias', 'backbone.16.multiplier', 'backbone.16.shift'}
    manifest = read_json(ROOT/'tmp/blue-plate-char-segment/experiment/dev-manifest.json')['records']
    report, selected = score_rows(read_json(OUT/'roi-predictions.json'), manifest, read_json(DEV/'gates.json'))
    assert report == read_json(OUT/'results.json')['fork_integer_with_float_ctc']
    assert selected == read_json(OUT/'selected.json')
    assert all(sha(ROOT/n) == h for n, h in read_json(OLD/'delivery-freeze.json')['artifacts'].items())
    audit = dict(saved_logits_replay_exact=True, selected_accumulators_numpy_int64_exact=accum.size,
        fork_outputs_fraction_exact=2*accum.size, full_context_output_unchanged=True,
        first_three_context_branches_unchanged=True, spatial_max_numpy_exact=True,
        requant_max_commutation_exact=True, fp32_channel_selection_exact=True,
        ddr_writes= writes, ddr_output_values_verified=253440, write_block_bytes=3840,
        two_slot_live_peak_bytes=304128, output_slot_reused_only_after_last_input_read=True,
        parameter_rows=320, changed_existing_arrays=changed_arrays,
        original_candidate_unchanged=True, fixed_scores_recounted=True,
        original_artifacts_unchanged=all(sha(OUT/n) == h for n, h in frozen.items()))
    write_json(OUT/'verification.json', audit)
    print(audit)


if __name__ == '__main__':
    main()
