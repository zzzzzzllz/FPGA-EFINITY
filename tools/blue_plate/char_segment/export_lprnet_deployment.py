"""ROI0 deployment trace, using the frozen config, parameters and integer kernels.

Export executes one manifest-driven integer forward. Verify only reads saved arrays;
it does not run the network. This is a research contract, not a hardware scheduler.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from ctc_interval import ceil_div, collapse, ctc_bounds, emissions, rank_candidates
from experiment import grammar
from integer_lprnet import round_ratio, round_tensor
from integer_lprnet_fork import FORK, TRUNK, ForkLPR

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'tmp/blue-plate-char-segment'
MODEL = DATA / 'quantization-tap2-fork'
CTC = DATA / 'ctc-q30'
DEFAULT = DATA / 'deployment-roi0'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def digest(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def plan(config):
    """References point into the existing config; no second model definition."""
    ops = [dict(kind='input', inputs=['input.bgr'], outputs=['input.q'])]
    current = 'input.q'
    for index, stage in enumerate(config['stages']):
        name = stage['name']
        if name == 'container.0':
            ops.append(dict(kind='concat', inputs=[f'context.{i}.normalized' for i in range(4)], outputs=['concat']))
            current = 'concat'
        outputs = [name, TRUNK, 'tap2.accumulator'] if name == FORK else [name]
        ops.append(dict(kind='fork' if name == FORK else stage['kind'], config_stage=index,
                        inputs=[TRUNK if name == 'backbone.14' else current], outputs=outputs))
        current = name
        if stage['tap'] is not None:
            i = stage['tap']
            ops.append(dict(kind='context', config_tap=str(i), inputs=[name],
                            outputs=[f'context.{i}.{suffix}' for suffix in ('average', 'energy', 'numerator', 'gain', 'normalized')]))
    ops.append(dict(kind='height_sum', inputs=['container.0'], outputs=['logits']))
    return ops


def run(ops, config, parameters, bgr):
    """Execute each backbone convolution once; context consumes each tap early."""
    assert bgr.dtype == np.uint8 and bgr.shape == (24, 94, 3)
    model = ForkLPR(config, parameters)
    values = {'input.bgr': bgr}
    statistics = {}
    for op in ops:
        kind = op['kind']
        source = values[op['inputs'][0]]
        if kind == 'input':
            result = torch.from_numpy((source.transpose(2, 0, 1).astype(np.int16)-128).astype(np.int8))[None]
            outputs = [result]
        elif kind == 'conv':
            result, stats = model.conv(source, config['stages'][op['config_stage']])
            statistics[op['outputs'][0]] = stats
            outputs = [result]
        elif kind == 'fork':
            (coarse, fine), stats, accum = model.fork_conv(source, config['stages'][op['config_stage']])
            statistics.update(stats)
            outputs = [coarse, fine, accum.T.reshape(coarse.shape).to(torch.int32)]
        elif kind == 'maxpool':
            stage = config['stages'][op['config_stage']]
            sh, sw = stage['spatial_stride']
            outputs = [source.unfold(2, 3, sh).unfold(3, 3, sw).amax(dim=(-1, -2))[:, ::stage['channel_stride']]]
        elif kind == 'context':
            meta = config['taps'][op['config_tap']]
            kh, kw = meta['kernel']
            sh, sw = meta['stride']
            centered = source.long()-meta['quantization']['zero']
            # Pass 1 determines E; pass 2 recomputes the same sums for normalization.
            window = lambda: centered.unfold(2, kh, sh).unfold(3, kw, sw).sum(dim=(-1, -2))
            first = window()
            energy = int(first.square().sum())
            if energy == 0:
                raise ValueError('Zero context energy')
            numerator = meta['constant_q30']*first.numel()
            gain = round_ratio(numerator, energy)
            second = window()
            assert torch.equal(first, second)
            product = second*gain
            assert int(product.max()) < 1 << 53
            unbounded = round_tensor(product, 1 << 30)+config['context']['zero']
            normalized = unbounded.clamp(-128, 127).to(torch.int8)
            outputs = [second, np.array(energy, np.uint64), np.array(numerator, np.uint64),
                       np.array(gain, np.uint64), normalized]
            statistics[op['outputs'][-1]] = dict(energy_sum=energy, numerator=numerator, gain_q30=gain,
                gain_bits=gain.bit_length(), multiply_abs_bound=int(product.max()), elements=normalized.numel(),
                saturated=int(((unbounded < -128) | (unbounded > 127)).sum()))
        elif kind == 'concat':
            outputs = [torch.cat([values[key] for key in op['inputs']], 1)]
        elif kind == 'height_sum':
            outputs = [(source.long()-config['stages'][-1]['output']['zero']).sum(dim=2).to(torch.int16)]
        else:
            raise ValueError(kind)
        values.update(zip(op['outputs'], outputs))
    arrays = {}
    for key, value in values.items():
        a = value.numpy() if isinstance(value, torch.Tensor) else value
        if key.endswith('.average'):
            assert int(a.min()) >= 0 and int(a.max()) <= 10200
            a = a.astype(np.uint16)
        arrays[key] = np.ascontiguousarray(a) if a.ndim else a.copy()
    return arrays, statistics


def confidence(logits, lut, classes):
    q = logits[0].astype(np.int32).T
    path = q.argmax(axis=1).tolist()  # Ties choose the lowest class ID.
    target = collapse(path, 67)
    code = ''.join(classes[i] for i in target)
    if not grammar(code) or len(target) != 7:
        raise ValueError('ROI0 must have a legal seven-character target')
    differences = q.max(axis=1, keepdims=True)-q
    assert 0 <= differences.min() <= differences.max() <= 1020
    scale = 1 << 30
    table = [(v, v if d == 0 else v+1) for d, v in enumerate(lut['lower'])]
    table += [tuple(lut['tail_bounds'])]*(1021-len(table))
    exp = np.array([[table[d] for d in row] for row in differences], np.uint32)
    probs = emissions(differences, table, 30)
    extended = [67]
    for c in target:
        extended.extend([c, 67])
    previous = [(scale, scale)]+[(0, 0)]*14
    states = [previous]
    for row in probs:
        current = []
        for s, c in enumerate(extended):
            sources = [previous[s]]
            if s:
                sources.append(previous[s-1])
            if s >= 2 and c != 67 and c != extended[s-2]:
                sources.append(previous[s-2])
            lower = sum(p[0] for p in sources)*row[c][0]//scale
            upper = min(scale, ceil_div(sum(p[1] for p in sources)*row[c][1], scale))
            current.append((lower, upper))
        states.append(current)
        previous = current
    bounds = (sum(p[0] for p in previous[-2:]), min(scale, sum(p[1] for p in previous[-2:])))
    assert bounds == ctc_bounds(probs, target, 30)
    threshold = lut['tau_power7_q30_bounds'][1]
    status = 'accept' if bounds[0] >= threshold else 'reject' if bounds[1] < threshold else 'undecided'
    arrays = {'ctc.greedy_path': np.array(path, np.uint8), 'ctc.target': np.array(target, np.uint8),
              'ctc.extended_target': np.array(extended, np.uint8), 'ctc.difference': differences.astype(np.uint16),
              'ctc.exp': exp, 'ctc.exp_sum': exp.astype(np.uint64).sum(axis=1),
              'ctc.emissions': np.array(probs, np.uint32), 'ctc.states': np.array(states, np.uint32),
              'ctc.bounds': np.array(bounds, np.uint32)}
    return arrays, dict(code=code, legal=True, greedy_path=path, decoded_ids=target,
                       bounds_q30=list(bounds), decision=status, combined_pass=True,
                       ranking=rank_candidates([dict(roi_index=0, bounds=bounds)]))


def tensor_meta(key, a, config):
    if a.ndim == 4:
        layout = 'NCHW'
    elif key == 'input.bgr':
        layout = 'HWC_BGR'
    elif key == 'logits':
        layout = 'NCT'
    else:
        layout = {'ctc.difference': 'TC', 'ctc.exp': 'TC_bounds', 'ctc.exp_sum': 'T_bounds',
                  'ctc.emissions': 'TC_bounds', 'ctc.states': 'initial_then_T_state_bounds'}.get(key, 'vector_or_scalar')
    meta = dict(shape=list(a.shape), dtype=a.dtype.str, layout=layout, elements=a.size,
                bytes=a.nbytes, sha256_c_order_bytes=digest(a))
    if key == 'input.q':
        meta['quantization'] = config['stages'][0]['input']
    elif key == TRUNK:
        meta['quantization'] = config['fork']['output']
    elif key in {s['name'] for s in config['stages']}:
        meta['quantization'] = next(s['output'] for s in config['stages'] if s['name'] == key)
    elif key == 'concat' or key.endswith('.normalized'):
        meta['quantization'] = config['context']
    elif key.endswith('.average'):
        meta.update(semantic='integer centered window SUM, not divided average', hardware_unsigned_bits=14,
                    quantization=dict(scale=config['taps'][key.split('.')[1]]['pool_scale'], zero=0))
    elif key == 'logits':
        meta['quantization'] = dict(scale=config['logit_scale'], zero=0)
    return meta


def enrich(ops, arrays, config, parameters):
    requants = []
    for number, op in enumerate(ops):
        op['id'] = number
        op['input_shapes'] = [list(arrays[k].shape) for k in op['inputs']]
        op['output_shapes'] = [list(arrays[k].shape) for k in op['outputs']]
        if op['kind'] in ('conv', 'fork'):
            stage = config['stages'][op['config_stage']]
            op.update(padding_hw=stage['padding'], padding_value=stage['input']['zero'], stride_hw=[1, 1],
                      kernel_hw=stage['kernel'], weight_layout='OIHW; K order input_channel, ky, kx',
                      accumulator='int32 seeded with stored zero-corrected bias; do not subtract input zero again',
                      requant='optional ReLU on accumulator; signed64 product; one RNE shift; add zero; int8 saturation',
                      parameter_keys={suffix: stage['name']+'.'+suffix for suffix in ('weight', 'bias', 'multiplier', 'shift')})
            names = [stage['name'], TRUNK] if op['kind'] == 'fork' else [stage['name']]
            if op['kind'] == 'fork':
                op['fork_contract'] = dict(channels_ref='config.fork.channels', fine_parameters=[TRUNK+'.multiplier', TRUNK+'.shift'],
                    source='Both branches use the same raw int32 accumulator; never requantize the coarse A8 into fine A8',
                    lifetime='Keep input until all fork reads; coarse until context pass2 ends; fine until pool14 last read',
                    raw_psum='Drain full K, save 8 original int32 in existing 32B slot; restore/capture before wide multiply; release after both consumers accept')
            for name in names:
                shifts = parameters[name+'.shift']
                per_channel = arrays[name].shape[0]*arrays[name].shape[2]*arrays[name].shape[3]
                unique, count = np.unique(shifts, return_counts=True)
                requants.append(dict(output=name, output_elements=arrays[name].size, outputs_per_channel=per_channel,
                    multiplier_key=name+'.multiplier', shift_key=name+'.shift', shift_array_sha256=digest(shifts),
                    shifts=[dict(right_shift=int(s), channels=int(n), outputs=int(n)*per_channel) for s, n in zip(unique, count)]))
        elif op['kind'] == 'maxpool':
            stage = config['stages'][op['config_stage']]
            op.update(kernel_hw=[3, 3], padding_hw=[0, 0], spatial_stride=stage['spatial_stride'],
                      channel_stride=stage['channel_stride'], semantics='Spatial max, then keep channel indices 0,stride,2*stride,...')
        elif op['kind'] == 'context':
            meta = config['taps'][op['config_tap']]
            op.update(kernel_hw=meta['kernel'], spatial_stride=meta['stride'], padding_hw=[0, 0],
                      input_center_zero=meta['quantization']['zero'], pass1='v=sum(q-zero); E=sum(v*v)',
                      gain='RNE(constant_q30 * output_elements / E); E=0 is an error',
                      pass2='Re-read same tap; recompute v; clip_int8(RNE(v*gain/2^30)+context.zero)',
                      widths=dict(window_unsigned=14, energy_unsigned=41, numerator_unsigned=53,
                                  gain_unsigned=53, product_container_unsigned=64, product_bound_exclusive=2**53),
                      lifetime='Hold raw tap through pass2; normalized A8 remains until projection consumes it')
            name = op['outputs'][-1]
            requants.append(dict(output=name, output_elements=arrays[name].size, right_shift=30,
                                 multiplier='runtime full-width gain', gain_golden_key=op['outputs'][3]))
        elif op['kind'] == 'concat':
            op['semantics'] = 'Logical channel order branch0,1,2,3; hardware reads separate HWC DDR regions without copying'
        elif op['kind'] == 'height_sum':
            op['semantics'] = 'Each of 4 rows already passed full K516 projection, RNE, zero63, A8 clipping; sum(q-63) into int16. No further requantization.'
    return requants


def complete_contract(manifest, arrays, parameters):
    """Attach transport and confidence metadata; does not run inference."""
    manifest['parameter_arrays'] = {key: dict(shape=list(a.shape), dtype=a.dtype.str,
        hardware_type={'weight': 'int8', 'bias': 'int32', 'multiplier': 'uint31', 'shift': 'uint6'}[key.rsplit('.', 1)[1]],
        sha256_c_order_bytes=digest(a)) for key, a in parameters.items()}
    locations = {'input.q': dict(slot=0, offset=0, bytes=arrays['input.q'].nbytes)}
    for op in manifest['operators']:
        kind = op['kind']
        if kind == 'input':
            op['transport'] = dict(write=locations['input.q'])
        elif kind in ('conv', 'fork', 'maxpool') and op['outputs'][0] != 'container.0':
            source = locations[op['inputs'][0]]
            destination = dict(slot=1-source['slot'], offset=0, bytes=arrays[op['outputs'][0]].nbytes)
            assert destination['bytes'] <= 262144
            locations[op['outputs'][0]] = destination
            op['transport'] = dict(read=source, write=destination)
            if kind == 'fork':
                locations[TRUNK] = dict(slot=destination['slot'], offset=202752, bytes=50688)
                op['transport']['fine_write'] = locations[TRUNK]
                assert 202752+50688 <= 262144
        elif kind == 'context':
            i = int(op['config_tap'])
            op['transport'] = dict(read_twice=locations[op['inputs'][0]],
                                   write_context_region=manifest['memory']['context_regions'][i])
        elif kind == 'conv':
            op['transport'] = dict(read='logical concat of four context regions',
                                   write='A8 block, at most 1088B for 16 points; accumulate centered values into existing logits banks')
    descriptions = [
        ('greedy', ['logits'], ['ctc.greedy_path'], 'Argmax over all 68 classes at each t; ties lowest ID'),
        ('collapse_and_grammar', ['ctc.greedy_path'], ['ctc.target', 'ctc.extended_target'],
         'Merge adjacent repeats then remove blank67; existing grammar must accept 7 characters; interleave blank into 15 states'),
        ('difference', ['logits'], ['ctc.difference'], 'd[t,c]=max_c(logit[c,t])-logit[c,t], uint16 range 0..1020'),
        ('exp_lookup', ['ctc.difference'], ['ctc.exp'], 'Frozen Q30 LUT: d0 exact; 1..70 lower,lower+1; d>=71 [0,1]'),
        ('sum_exp', ['ctc.exp'], ['ctc.exp_sum'], 'Sum all 68 lower and upper bounds independently, uint64 container'),
        ('emissions', ['ctc.exp', 'ctc.exp_sum'], ['ctc.emissions'],
         'L=floor(expL*2^30/sumU); U=min(2^30,ceil(expU*2^30/sumL)); uint64 dividends'),
        ('ctc_dp', ['ctc.emissions', 'ctc.extended_target'], ['ctc.states'],
         'Initial state0=[2^30,2^30], others0; self, previous1, allowed previous2; outward multiply; two separate rows'),
        ('ctc_final', ['ctc.states'], ['ctc.bounds'], 'Sum final two states, clamp upper at 2^30'),
    ]
    manifest['confidence_operators'] = [dict(kind=kind, inputs=ins, outputs=outs, semantics=semantic,
        input_shapes=[list(arrays[k].shape) for k in ins], output_shapes=[list(arrays[k].shape) for k in outs])
        for kind, ins, outs, semantic in descriptions]
    manifest['confidence_operators'].append(dict(kind='decision_and_ranking', inputs=['ctc.bounds'], outputs=[],
        input_shapes=[[2]], output_shapes=[],
        semantics='L>=1023453813 accept; U<1023453813 reject; otherwise undecided. Across legal eligible ROIs use frozen rank_candidates; overlap is undecided unless a tie is proved. Emit accepted code only after both rank and threshold are decided.'))
    manifest['requantization_totals'] = dict(
        convolution_and_fork=sum(r['output_elements'] for r in manifest['requantization'] if 'shift_key' in r),
        context=sum(r['output_elements'] for r in manifest['requantization'] if 'gain_golden_key' in r),
        all=sum(r['output_elements'] for r in manifest['requantization']))
    manifest['sources'].update({relative(ROOT/p): sha(ROOT/p) for p in [
        'tools/blue_plate/compare_hyperlpr.py', 'tools/blue_plate/baseline.py',
        'docs/validation/blue-plate/char-segment/integer-deployment-addendum.md',
        'tmp/blue-plate-char-segment/integer-deployment-audit/report.json',
        'tmp/blue-plate-char-segment/integer-deployment-audit/output-channel-mac-vectors.npz']})


def verify(output):
    manifest = read(output/'manifest.json')
    for path, expected in manifest['sources'].items():
        assert sha(ROOT/path) == expected, path
    assert sha(output/'golden.npz') == manifest['golden_sha256']
    with np.load(output/'golden.npz', allow_pickle=False) as z:
        assert set(z.files) == set(manifest['tensors'])
        for key, meta in manifest['tensors'].items():
            a = z[key]
            assert list(a.shape) == meta['shape'] and a.dtype.str == meta['dtype'], key
            assert digest(a) == meta['sha256_c_order_bytes'], key
        available = {'input.bgr'}
        for op in manifest['operators']+manifest['confidence_operators']:
            assert set(op['inputs']) <= available, op['kind']
            assert [list(z[k].shape) for k in op['inputs']] == op['input_shapes']
            assert [list(z[k].shape) for k in op['outputs']] == op['output_shapes']
            available.update(op['outputs'])
        for region in manifest['memory']['context_regions']:
            a = z[f"context.{region['branch']}.normalized"][0]
            rows = a.transpose(1, 2, 0).reshape(4, -1)
            packed = np.zeros((4, region['row_pitch']), np.int8)
            packed[:, :rows.shape[1]] = rows
            assert packed.nbytes == region['bytes']
            np.testing.assert_array_equal(packed[:, :rows.shape[1]].reshape(4, 18, region['channels']).transpose(2, 0, 1), a)
        with np.load(MODEL/'integer-parameters.npz', allow_pickle=False) as params:
            for key, meta in manifest['parameter_arrays'].items():
                assert list(params[key].shape) == meta['shape'] and params[key].dtype.str == meta['dtype']
                assert digest(params[key]) == meta['sha256_c_order_bytes']
            for r in manifest['requantization']:
                assert r['output_elements'] == z[r['output']].size
                if 'shift_key' in r:
                    values, counts = np.unique(params[r['shift_key']], return_counts=True)
                    expected = [dict(right_shift=int(v), channels=int(n), outputs=int(n)*r['outputs_per_channel']) for v,n in zip(values,counts)]
                    assert r['shifts'] == expected
        with np.load(MODEL/'integer-logits.npz', allow_pickle=False) as reference:
            np.testing.assert_array_equal(z['logits'][0], reference['logits'][0])
        with np.load(MODEL/'fork-vectors.npz', allow_pickle=False) as reference:
            checks = {'input': 'backbone.11.block.4', 'context': FORK, 'trunk': TRUNK, 'pooled': 'backbone.14'}
            for old, new in checks.items():
                np.testing.assert_array_equal(z[new], reference[old])
            np.testing.assert_array_equal(z['tap2.accumulator'][:, ::4], reference['accumulator'])
        expected_arrays, result = confidence(z['logits'], read(CTC/'lut.json'), read(DATA/'pretrained-new-rois/config.json')['classes'])
        for key, a in expected_arrays.items():
            np.testing.assert_array_equal(z[key], a)
    prior = read(MODEL/'roi-predictions.json')[0]
    q30 = read(CTC/'development-roi-intervals.json')[0]
    assert result['code'] == prior['code'] == q30['code']
    assert result['greedy_path'] == prior['greedy_path'] and result['decoded_ids'] == prior['decoded_ids']
    assert result['bounds_q30'] == [q30['probability_lower_q30'], q30['probability_upper_q30']]
    assert result['decision'] == q30['acceptance_status'] and result['combined_pass'] == q30['combined_pass']
    assert result == manifest['result']
    return dict(pass_all=True, integer_network_forwards=0, sources_checked=len(manifest['sources']),
                tensors_checked=len(manifest['tensors']), frozen_logits_exact=True, frozen_fork_vectors_exact=True,
                q30_states_replayed=True, frozen_code_decision_interval_exact=True,
                dependency_shapes_checked=True, context_ddr_roundtrip=True, parameter_shifts_counts_checked=True, result=result)


def export(output):
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite {output}')
    config = read(MODEL/'integer-config.json')
    sources = [MODEL/'integer-config.json', MODEL/'integer-parameters.npz', MODEL/'integer-logits.npz',
        MODEL/'fork-vectors.npz', MODEL/'roi-predictions.json', MODEL/'delivery-freeze.json',
        CTC/'lut.json', CTC/'finite-interface.json', CTC/'development-roi-intervals.json', CTC/'delivery-freeze.json',
        DATA/'pretrained-new-rois/q8_bgr-inputs.npz', DATA/'pretrained-new-rois/config.json',
        Path(__file__), Path(__file__).with_name('integer_lprnet.py'), Path(__file__).with_name('integer_lprnet_fork.py'),
        Path(__file__).with_name('ctc_interval.py'), Path(__file__).with_name('experiment.py')]
    hashes = {relative(p): sha(p) for p in sources}
    with np.load(MODEL/'integer-parameters.npz', allow_pickle=False) as p:
        parameters = {key: p[key] for key in p.files}
    with np.load(DATA/'pretrained-new-rois/q8_bgr-inputs.npz', allow_pickle=False) as z:
        bgr = z['bgr'][0].copy()
    ops = plan(config)
    arrays, statistics = run(ops, config, parameters, bgr)
    q30_arrays, result = confidence(arrays['logits'], read(CTC/'lut.json'), read(DATA/'pretrained-new-rois/config.json')['classes'])
    arrays.update(q30_arrays)
    requants = enrich(ops, arrays, config, parameters)
    output.mkdir(parents=True)
    np.savez_compressed(output/'golden.npz', **arrays)
    manifest = dict(roi_index=0, sample_index=1, integer_network_forwards=1,
        sources=hashes, config_ref=relative(MODEL/'integer-config.json'), parameters_ref=relative(MODEL/'integer-parameters.npz'),
        golden_sha256=sha(output/'golden.npz'), tensors={k: tensor_meta(k, v, config) for k, v in arrays.items()},
        operators=ops, requantization=requants, statistics=statistics, result=result,
        runtime_contract=read(CTC/'finite-interface.json'),
        execution='operators run in listed order; config_stage/config_tap resolve original config; golden captures are host-only',
        confidence_execution='confidence() consumes logits, frozen LUT, class mapping; exported 19 DP rows include initialization; repeated target forbids skip-2',
        unresolved='Threshold or ranking interval overlap returns explicit undecided, selected code must not be guessed; synthetic ROI7/283 remains undecided',
        memory=dict(relative_arena_bytes=7052352, ram_banks=51, dsp=8, physical_addresses=None,
            feature_slot_bytes=262144, feature_slot_count=2, feature_layout='HWC, channel contiguous, packed rows',
            feature_address='feature_region_base + slot*262144 + offset + (h*W+w)*C+c; bases remain symbolic',
            nchw_to_hwc='golden[n,c,h,w] maps to byte (h*W+w)*C+c within its assigned feature slot',
            fork_output=dict(coarse_offset=0, coarse_bytes=202752, fine_offset=202752, fine_bytes=50688,
                             block_positions=12, coarse_block_bytes=3072, fine_block_bytes=768),
            context_regions=[dict(branch=i, relative_offset=o, row_pitch=p, bytes=b, channels=c)
                for i,o,p,b,c in [(0,0,1152,4608,64),(1,4608,2304,9216,128),(2,13824,4608,18432,256),(3,32256,1232,4928,68)]],
            context_total_bytes=37184, context_address='context_base + relative_offset + h*row_pitch + t*channels + c; padding never consumed',
            concat='logical only; do not allocate golden concat, full tap set, full accumulator, or full CTC history on device',
            logits='int16 C,T; offset 2*(c*18+t), 2448 bytes in existing logits banks',
            allocation_reference='docs/validation/blue-plate/char-segment/integer-deployment-addendum.md'),
        latency='No new latency estimate; exact output counts and original per-channel shift references provided for resource-window accounting')
    complete_contract(manifest, arrays, parameters)
    write(output/'manifest.json', manifest)
    report = verify(output)
    write(output/'verification.json', report)
    print(json.dumps(dict(output=relative(output), tensors=len(arrays), operators=len(ops),
                         requantizations=sum(r['output_elements'] for r in requants), result=result), ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['export', 'verify'])
    parser.add_argument('--output', type=Path, default=DEFAULT)
    args = parser.parse_args()
    torch.set_num_threads(4)
    if args.mode == 'export':
        export(args.output.resolve())
    else:
        print(json.dumps(verify(args.output.resolve()), ensure_ascii=True))
