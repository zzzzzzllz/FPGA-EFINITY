"""Independent scalar/NumPy checks of the frozen integer arithmetic and MAC vectors."""
from fractions import Fraction

import numpy as np
import torch

from experiment import ROOT, read_json, write_json, sha
from integer_lprnet import IntegerLPR, round_ratio, round_tensor

OUT = ROOT/'tmp/blue-plate-char-segment/quantization-w8a8'


def main():
    torch.set_num_threads(4)
    frozen = read_json(OUT/'frozen.json')['artifacts']
    assert all(sha(OUT/name) == digest for name, digest in frozen.items())
    config = read_json(OUT/'integer-config.json')
    arrays = dict(np.load(OUT/'integer-parameters.npz'))
    model = IntegerLPR(config, arrays)
    resized = np.load(ROOT/'tmp/blue-plate-char-segment/pretrained-new-rois/q8_bgr-inputs.npz')['bgr'][0]
    logits, trace, _, _ = model(resized)
    assert np.array_equal(logits[0].numpy(), np.load(OUT/'integer-logits.npz')['logits'][0])
    # Independent full first convolution: NumPy int64 matmul and scalar Fraction rounding.
    stage = config['stages'][0]
    x = resized.transpose(2, 0, 1).astype(np.int64)-128
    view = np.lib.stride_tricks.sliding_window_view(x, (3, 3), axis=(1, 2))
    patches = view.transpose(1, 2, 0, 3, 4).reshape(-1, 27)
    weights = arrays['backbone.0.weight'].astype(np.int64).reshape(64, 27)
    accum = patches@weights.T + arrays['backbone.0.bias']
    product = np.maximum(accum, 0)*arrays['backbone.0.multiplier']
    denominator = np.left_shift(np.ones(64, np.int64), arrays['backbone.0.shift'])
    quotient, remainder = np.divmod(product, denominator)
    quotient += (2*remainder > denominator) | ((2*remainder == denominator) & ((quotient & 1) != 0))
    expected = np.clip(quotient+stage['output']['zero'], -128, 127).astype(np.int8).T.reshape(1, 64, 22, 92)
    assert np.array_equal(expected, trace['backbone.0'][0].numpy())
    for i, meta in config['taps'].items():
        x = trace[meta['stage']][0].numpy().astype(np.int64)-meta['quantization']['zero']
        windows = np.lib.stride_tricks.sliding_window_view(x, tuple(meta['kernel']), axis=(2, 3))
        sh, sw = meta['stride']
        pooled = windows[:, :, ::sh, ::sw].sum(axis=(-1, -2))
        assert np.array_equal(pooled, trace[f'context.{i}.average'][0].numpy())
        energy = sum(int(v)**2 for v in pooled.flat)
        gain = round(Fraction(meta['constant_q30']*pooled.size, energy))
        normalized = np.array([max(-128, min(127, round(Fraction(int(v)*gain, 1 << 30))
                                    +config['context']['zero'])) for v in pooled.flat], dtype=np.int8).reshape(pooled.shape)
        assert np.array_equal(normalized, trace[f'context.{i}.normalized'][0].numpy())
    head = trace['container.0'][0].numpy().astype(np.int64)-config['stages'][-1]['output']['zero']
    assert np.array_equal(head.sum(axis=2), logits.numpy())
    rng = np.random.default_rng(701)
    rounding_cases = 0
    for denominator in (2, 4, 16, 1 << 30, 1 << 57):
        numerators = [int(v) for v in rng.integers(-(1 << 60), 1 << 60, 100, dtype=np.int64)]
        numerators += [k*denominator+denominator//2 for k in range(-5, 6)]
        actual = round_tensor(torch.tensor(numerators, dtype=torch.int64), denominator).tolist()
        expected = [round(Fraction(n, denominator)) for n in numerators]
        assert actual == expected
        assert all(round_ratio(n, denominator) == e for n, e in zip(numerators, expected))
        rounding_cases += len(actual)
    metadata = read_json(OUT/'real-mac-vectors.json')
    vectors = np.load(OUT/'real-mac-vectors.npz')
    cycles = 0
    for v in metadata['records']:
        prefix = f'v{v["index"]:02d}.'
        accumulator = v['initial_accumulator']
        for a, w, valid, expected in zip(vectors[prefix+'a'], vectors[prefix+'w'], vectors[prefix+'valid'], vectors[prefix+'accumulator_after']):
            accumulator += sum(int(x)*int(y) for x, y, mask in zip(a, w, valid) if int(mask))
            assert accumulator == int(expected)
            cycles += 1
        assert accumulator == v['accumulator']
        n = (max(0, accumulator) if v['relu'] else accumulator)*v['multiplier']
        expected = max(-128, min(127, round(Fraction(n, 1 << v['right_shift']))+v['output_zero']))
        assert expected == v['requantized']
        output = trace[v['layer']][0].numpy().reshape(trace[v['layer']][0].shape[1], -1)
        assert expected == int(output[v['channel'], v['position']])
    for k in (27, 516, 3328):
        for a, w in ((-128, 127), (127, -127), (-128, -127), (127, 127)):
            actual = torch._int_mm(torch.full((16, k), a, dtype=torch.int8), torch.full((k, 8), w, dtype=torch.int8))
            assert torch.all(actual == a*w*k)
    audit = dict(saved_parameter_replay_exact=True, full_first_conv_numpy_int64_exact=True,
                 four_context_branches_numpy_fraction_exact=True, integer_height_sum_exact=True,
                 rational_rounding_cases=rounding_cases, real_mac_dots=len(metadata['records']),
                 real_mac_cycles=cycles, real_requantized_outputs_match=True, extreme_signed_mm_cases=12,
                 original_artifacts_unchanged=all(sha(OUT/name) == digest for name, digest in frozen.items()))
    write_json(OUT/'verification.json', audit)
    print(audit)


if __name__ == '__main__':
    main()
