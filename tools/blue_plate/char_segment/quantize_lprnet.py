"""One train207-calibrated W8/A8 candidate and bounded layer diagnostics. No optimizer."""
from collections import defaultdict
import math
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F
from torch.nn.utils.fusion import fuse_conv_bn_weights

from experiment import ROOT, read_json, write_json, sha
from fixed_lprnet import FixedLPRNet, STRICT_THRESHOLD
from pretrained_new_rois import decode
from integer_lprnet import graph, FloatTrace, make_parameters, IntegerLPR, dequantize, round_ratio, round_tensor, POOLS

OUT = ROOT/'tmp/blue-plate-char-segment/quantization-w8a8'
DEV = ROOT/'tmp/blue-plate-char-segment/pretrained-new-rois'
INPUT = ROOT/'tmp/blue-plate-char-segment/experiment'


def score_rows(predictions, manifest, gates):
    groups = defaultdict(list)
    for p, r in zip(predictions, manifest):
        groups[r['sample_index']].append((p, r))
    report, selections = {}, {}
    for mode in ('ocr_only', 'combined'):
        selected = []
        for sample, rows in groups.items():
            allowed = [(p, r) for p, r in rows if p['legal'] and (mode == 'ocr_only' or gates[r['roi_index']]['combined_pass'])]
            best = max(allowed, key=lambda item: (item[0]['score'], -item[1]['roi_index'])) if allowed else None
            selected.append(dict(sample_index=sample, split=rows[0][1]['split'], label=rows[0][1]['source_transcript'],
                code=best[0]['code'] if best else None, score=best[0]['score'] if best else None,
                roi_index=best[1]['roi_index'] if best else None))
        result = {}
        for subset, rows in [('development', selected), ('tune', [r for r in selected if r['split'] == 'tune'])]:
            for point, threshold in [('raw_legal', 0.), ('strict', STRICT_THRESHOLD)]:
                accepted = [r for r in rows if r['score'] is not None and r['score'] >= threshold]
                correct = sum(r['code'] == r['label'] for r in accepted)
                result[subset+'_'+point] = dict(total=len(rows), correct=correct, wrong=len(accepted)-correct,
                                               rejected=len(rows)-len(accepted))
        report[mode], selections[mode] = result, selected
    return report, selections


def write_vectors(vectors):
    arrays, records = {}, []
    for i, vector in enumerate(vectors):
        v = dict(vector)
        a, w = v.pop('a'), v.pop('w')
        padded = (len(a)+7)//8*8
        aa, ww = np.zeros(padded, np.int8), np.zeros(padded, np.int8)
        valid = np.zeros(padded, np.uint8)
        aa[:len(a)], ww[:len(w)], valid[:len(a)] = a, w, 1
        acc = v['initial_accumulator']
        partial = []
        for start in range(0, padded, 8):
            acc += sum(int(x)*int(y) for x, y in zip(aa[start:start+8], ww[start:start+8]))
            partial.append(acc)
        assert acc == v['accumulator']
        y = round_ratio(max(acc, 0) * v['multiplier'] if v['relu'] else acc*v['multiplier'], 1 << v['right_shift'])
        v.update(index=i, terms=len(a), cycles=padded//8, requantized=int(np.clip(y+v['output_zero'], -128, 127)))
        for key, value in dict(a=aa.reshape(-1, 8), w=ww.reshape(-1, 8), valid=valid.reshape(-1, 8),
                               accumulator_after=np.array(partial, np.int32)).items():
            arrays[f'v{i:02d}.{key}'] = value
        records.append(v)
    np.savez_compressed(OUT/'real-mac-vectors.npz', **arrays)
    write_json(OUT/'real-mac-vectors.json', dict(source_roi_index=0, lanes=8, records=records,
        semantics='accumulator starts at bias including input-zero correction; signed int8 dot products; invalid tail lanes zero'))


def fusion_error(net, stages, fp):
    modules = dict(net.named_modules())
    previous = fp['input']
    errors = {}
    for s in stages:
        if s['kind'] == 'conv':
            conv = modules[s['name']]
            w, b = conv.weight, conv.bias
            if s['bn'] is not None:
                bn = modules[s['bn']]
                w, b = fuse_conv_bn_weights(w, b, bn.running_mean, bn.running_var, bn.eps, bn.weight, bn.bias)
            x = fp['concat'] if s['name'] == 'container.0' else previous
            if s['name'] == 'backbone.0':
                x = x-1/256
                b = b+w.sum(dim=(1, 2, 3))/256
            y = F.conv2d(x, w, b, padding=tuple(s['padding']))
            if s['relu']:
                y = y.relu()
            errors[s['name']] = float((y-fp[s['name']]).abs().max())
        previous = fp[s['name']]
    return errors


def main():
    if OUT.exists():
        raise FileExistsError(f'Preserve fixed experiment: {OUT}')
    OUT.mkdir()
    started = time.monotonic()
    torch.set_num_threads(4)
    train_config = INPUT.parent/'bn-calibration/config.json'
    train = read_json(train_config)['train_indices']
    manifest = read_json(INPUT/'dev-manifest.json')['records']
    assert len(train) == len(set(train)) == 207
    assert all(manifest[i]['split'] == 'train' for i in train)
    assert all(r['original_split'] == 'development' for r in manifest)
    sources = [Path(__file__), Path(__file__).with_name('integer_lprnet.py'), Path(__file__).with_name('fixed_lprnet.py'),
        Path(__file__).with_name('pretrained_new_rois.py'), INPUT/'dev-manifest.json', DEV/'q8_bgr-inputs.npz',
        DEV/'q8_bgr-logits.npz', DEV/'q8_bgr-roi-records.json', DEV/'gates.json', train_config,
        ROOT/'docs/validation/blue-plate/char-segment/quantization-plan.md']
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in sources}
    write_json(OUT/'protocol.json', dict(source_hashes=hashes, calibration_roi_indices=train,
        calibration_count=207, evaluation_roi_count=307, threshold=STRICT_THRESHOLD, threshold_fit=False,
        validation_image_reads=0, heldout_image_reads=0, optimizer_steps=0,
        candidate='one per-output-channel W8 / affine per-tensor A8 minmax candidate',
        system_status='mixed precision diagnostic: integer neural arithmetic, floating host log-softmax/CTC',
        known_rejection_failure='strict full-frame middle occlusion accepted 66/388; quantization does not fix completeness'))
    # Signed ties, half boundaries, and saturation are not delegated to host floating point.
    for denominator in (2, 4, 16, 1 << 30):
        n = torch.tensor([-2*denominator-1, -denominator-denominator//2, -denominator//2,
                          0, denominator//2, denominator+denominator//2, 2*denominator+1], dtype=torch.int64)
        assert round_tensor(n, denominator).tolist() == [round_ratio(int(v), denominator) for v in n]
    runner = FixedLPRNet()
    net = runner.net
    state = {k: v.clone() for k, v in net.state_dict().items()}
    stages = graph(net)
    observer = FloatTrace(net, stages)
    images = np.load(DEV/'q8_bgr-inputs.npz')['bgr']
    frozen_logits = np.load(DEV/'q8_bgr-logits.npz')['logits']
    frozen_predictions = read_json(DEV/'q8_bgr-roi-records.json')
    gates = read_json(DEV/'gates.json')
    ranges = {}
    with torch.inference_mode():
        for step, i in enumerate(train):
            values = observer(images[i])
            for name, x in values.items():
                lo, hi = float(x.min()), float(x.max())
                old = ranges.get(name, (lo, hi))
                ranges[name] = (min(old[0], lo), max(old[1], hi))
            if step % 50 == 0:
                print('calibration train ROI', step+1, '/207', flush=True)
        config, arrays = make_parameters(net, stages, ranges)
        write_json(OUT/'calibration-ranges.json', ranges)
        write_json(OUT/'integer-config.json', config)
        np.savez_compressed(OUT/'integer-parameters.npz', **arrays)
        parameter_hashes = {p.name: sha(p) for p in [OUT/'calibration-ranges.json', OUT/'integer-config.json', OUT/'integer-parameters.npz']}
        write_json(OUT/'parameter-freeze.json', dict(calibration_roi_indices=train, artifacts=parameter_hashes,
                                                   frozen_before_development_evaluation=True))
        integer = IntegerLPR(config, arrays)
        predictions, integer_logits, per_roi, ranges_integer, errors = [], [], [], {}, {}
        fusion_checks = {}
        for i, resized in enumerate(images):
            fp = observer(resized)
            assert np.array_equal(fp['logits'][0].numpy(), frozen_logits[i])
            qlogits, trace, statistics, vectors = integer(resized, capture_vectors=i == 0)
            if i == 0:
                write_vectors(vectors)
            if i in (0, 13, 306):
                fusion_checks[str(i)] = fusion_error(net, stages, fp)
            roi_errors = {}
            for name, item in trace.items():
                actual = dequantize(item)
                reference = fp[name].double()
                assert actual.shape == reference.shape
                delta = actual-reference
                se, sr = float(delta.square().sum()), float(reference.square().sum())
                mae, maximum = float(delta.abs().sum()), float(delta.abs().max())
                aggregate = errors.setdefault(name, dict(squared_error=0., squared_reference=0., absolute_error=0., elements=0, max_abs=0.))
                for key, value in [('squared_error', se), ('squared_reference', sr), ('absolute_error', mae), ('elements', actual.numel())]:
                    aggregate[key] += value
                aggregate['max_abs'] = max(aggregate['max_abs'], maximum)
                roi_errors[name] = dict(relative_rmse=math.sqrt(se/sr) if sr else None, max_abs=maximum)
                q = item[0]
                entry = ranges_integer.setdefault(name, dict(minimum=int(q.min()), maximum=int(q.max())))
                entry['minimum'] = min(entry['minimum'], int(q.min()))
                entry['maximum'] = max(entry['maximum'], int(q.max()))
            logits = qlogits[0].double()*config['logit_scale']
            decoded = decode(logits, runner.chars)
            predictions.append(dict(roi_index=i, **decoded))
            integer_logits.append(qlogits[0].numpy())
            per_roi.append(dict(roi_index=i, split=manifest[i]['split'], errors=roi_errors, arithmetic=statistics,
                                greedy_changed=decoded['code'] != frozen_predictions[i]['code']))
            if i % 50 == 0:
                print('integer development ROI', i+1, '/307', flush=True)
        for record in errors.values():
            record['relative_rmse'] = math.sqrt(record['squared_error']/record['squared_reference']) if record['squared_reference'] else None
            record['mean_abs'] = record['absolute_error']/record['elements']
        report, selected = score_rows(predictions, manifest, gates)
        baseline, old_selected = score_rows(frozen_predictions, manifest, gates)
        write_json(OUT/'roi-predictions.json', predictions)
        write_json(OUT/'roi-layer-errors.json', per_roi)
        write_json(OUT/'selected.json', selected)
        np.savez_compressed(OUT/'integer-logits.npz', logits=np.stack(integer_logits))
        write_json(OUT/'layer-summary.json', dict(errors=errors, integer_ranges=ranges_integer, fusion_checks=fusion_checks))
        result = dict(fp32=baseline, integer_with_float_ctc=report,
            greedy_changed=sum(r['greedy_changed'] for r in per_roi), fusion_max_abs=max(max(v.values()) for v in fusion_checks.values()),
            logit_scale=config['logit_scale'], parameter_hashes=parameter_hashes, diagnostics={})
        lost_raw = baseline['ocr_only']['development_raw_legal']['correct']-report['ocr_only']['development_raw_legal']['correct']
        lost_strict = baseline['ocr_only']['development_strict']['correct']-report['ocr_only']['development_strict']['correct']
        if max(lost_raw, lost_strict) > 5:
            # These isolate locations using the SAME parameters, not new quantization candidates.
            diagnostic_predictions = {name: [] for name in ('integer_backbone_float_context_head', 'float_backbone_integer_context_head')}
            for i, resized in enumerate(images):
                fp = observer(resized)
                _, quantized_trace, _, _ = integer(resized)
                normals = []
                taps = {}
                for stage in stages:
                    if stage['tap'] is None:
                        continue
                    branch = stage['tap']
                    x = dequantize(quantized_trace[stage['name']]).float()
                    avg = F.avg_pool2d(x, *POOLS[branch])
                    normals.append(avg/avg.square().mean())
                    qparams = config['taps'][str(branch)]['quantization']
                    taps[branch] = (torch.round(fp[stage['name']].double()/qparams['scale'])+qparams['zero']).clamp(-128, 127).to(torch.int8)
                float_head = net.container(torch.cat(normals, 1)).mean(dim=2)[0]
                diagnostic_predictions['integer_backbone_float_context_head'].append(dict(roi_index=i, **decode(float_head, runner.chars)))
                quant_head = integer.context_head(taps, {}, {})[0].double()*config['logit_scale']
                diagnostic_predictions['float_backbone_integer_context_head'].append(dict(roi_index=i, **decode(quant_head, runner.chars)))
                if i % 100 == 0:
                    print('fixed-parameter localization ROI', i+1, '/307', flush=True)
            for name, values in diagnostic_predictions.items():
                write_json(OUT/f'{name}-predictions.json', values)
                result['diagnostics'][name] = score_rows(values, manifest, gates)[0]
        assert all(torch.equal(state[k], v) for k, v in net.state_dict().items())
        assert all(sha(OUT/name) == digest for name, digest in parameter_hashes.items())
        assert all(sha(ROOT/name) == digest for name, digest in hashes.items())
        result.update(model_state_unchanged=True, parameters_unchanged_after_freeze=True, elapsed_seconds=time.monotonic()-started,
                      validation_image_reads=0, heldout_image_reads=0, optimizer_steps=0)
        observer.close()
        write_json(OUT/'results.json', result)
        write_json(OUT/'frozen.json', dict(artifacts={p.name: sha(p) for p in OUT.iterdir() if p.is_file()}))
        print(result, flush=True)


if __name__ == '__main__':
    main()
