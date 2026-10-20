"""Fixed public LPRNet on development-only detector320/Q32 BGR crops. No training."""
import ast
from collections import defaultdict
import importlib.util
import math
from pathlib import Path
import time

import cv2
import numpy as np
import torch
from torch.nn import functional as F

from experiment import ROOT, DETECTOR, read_json, write_json, sha, array_sha, resize_q8, grammar

OUT = ROOT / 'tmp/blue-plate-char-segment/pretrained-new-rois'
INPUT = ROOT / 'tmp/blue-plate-char-segment/experiment'
PUBLIC = ROOT / 'tmp/blue-plate-review/mature-research/lprnet'


def decode(logits, chars):
    path = logits.argmax(0).tolist()
    target = [c for i, c in enumerate(path) if c != 67 and (i == 0 or c != path[i-1])]
    logp = logits.double().log_softmax(0).T[:, None, :]
    loss = F.ctc_loss(logp, torch.tensor(target, dtype=torch.long), [len(path)],
                      [len(target)], blank=67, reduction='sum', zero_infinity=False)
    assert torch.isfinite(loss)
    code = ''.join(chars[c] for c in target)
    return dict(code=code, greedy_path=path, decoded_ids=target, legal=bool(grammar(code)),
                sequence_log_probability=-loss.item(),
                score=math.exp(-loss.item()/7) if grammar(code) else None)


def metrics(rows, threshold):
    counts = dict(correct=0, wrong=0, rejected=0, total=len(rows))
    for r in rows:
        if r['roi_index'] is None or r['score'] < threshold:
            counts['rejected'] += 1
        else:
            counts['correct' if r['code'] == r['label'] else 'wrong'] += 1
    return counts


def calibrate(rows, max_wrong):
    thresholds = sorted({0., 1.000001} | {r['score'] for r in rows if r['score'] is not None})
    options = [(t, metrics(rows, t)) for t in thresholds]
    t, m = max(((t, m) for t, m in options if m['wrong'] <= max_wrong),
               key=lambda item: (item[1]['correct'], -item[1]['wrong'], -item[0]))
    return dict(threshold=t, development=m,
                tune=metrics([r for r in rows if r['split'] == 'tune'], t))


def frozen_gates(manifest):
    frames = {r['sample_index']: r for r in read_json(DETECTOR/'fullframe-rejection/records.json')
              if r['kind'] == 'positive' and r['split'] == 'development'}
    colors = {r['sample_index']: r for r in read_json(DETECTOR/'color-evidence-development/records.json')
              if r['kind'] == 'development_positive_frame'}
    assert len(frames) == len(colors) == 304
    gates = []
    for r in manifest:
        frame = frames[r['sample_index']]
        assert frame['source'] == r['path']
        assert len(frame['outputs']) == len(colors[r['sample_index']]['outputs'])
        p = frame['outputs'][r['candidate_index']]
        c = colors[r['sample_index']]['outputs'][r['candidate_index']]
        assert p['points'] == r['points'] == r['teacher_cached']['points']
        assert p['box'] == r['teacher_cached']['box']
        assert p['code'] == c['code'] == r['teacher_cached']['code']
        assert abs(p['confidence'] - c['confidence']) < 1e-12
        hs = c['color_evidence']
        assert hs['hs_blue_over_yellow'] == (hs['counts']['blue_hs'] > hs['counts']['yellow_hs'])
        blue = p['color_class'] == 0
        inside = p['corner_margin'] >= 1 and p['box_margin'] >= 1
        gates.append(dict(roi_index=r['roi_index'], sample_index=r['sample_index'],
                          candidate_index=r['candidate_index'], color_class=p['color_class'],
                          hs_blue_over_yellow=hs['hs_blue_over_yellow'],
                          blue_count=hs['counts']['blue_hs'], yellow_count=hs['counts']['yellow_hs'],
                          corner_margin=p['corner_margin'], box_margin=p['box_margin'],
                          combined_pass=bool(blue and inside and hs['hs_blue_over_yellow'])))
    return gates


def main():
    started = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    sources = [Path(__file__), INPUT/'dev-inputs.npz', INPUT/'dev-manifest.json',
               PUBLIC/'model/LPRNet.py', PUBLIC/'data/load_data.py',
               PUBLIC/'weights/Final_LPRNet_model.pth', Path(__file__).with_name('experiment.py'),
               DETECTOR/'fullframe-rejection/records.json',
               DETECTOR/'color-evidence-development/records.json',
               DETECTOR/'color-candidate-confirmation/candidate-freeze.json']
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in sources}
    assert sha(PUBLIC/'model/LPRNet.py') == '94a49696268ff942d92d58285ddeacab9b2ef35a4102bd73862518729e0dfc14'
    assert sha(PUBLIC/'weights/Final_LPRNet_model.pth') == 'd1ca22ca7a251a90702a166c8ad8ce7f05acb39f5ef8055139a33d462716d1ad'
    assert sha(INPUT/'dev-inputs.npz') == 'e82bae6766fd98135f10e2c383d63f65e165b1c13d64b4d432eefc843a5bd0be'
    assert sha(INPUT/'dev-manifest.json') == 'd09091e14067c0d4ce2ed5dca9d2f10c951a70e6a42d4d4fecb4144a1c96a9b6'
    manifest = read_json(INPUT/'dev-manifest.json')['records']
    images = np.load(INPUT/'dev-inputs.npz')['bgr']
    assert images.shape == (307, 64, 224, 3) and images.dtype == np.uint8
    assert len({r['sample_index'] for r in manifest}) == 304
    assert len({r['sample_index'] for r in manifest if r['split'] == 'tune'}) == 76
    for i, r in enumerate(manifest):
        assert r['roi_index'] == i and r['original_split'] == 'development'
        assert array_sha(images[i]) == r['roi_bgr_sha256']
    tree = ast.parse((PUBLIC/'data/load_data.py').read_text(encoding='utf8'))
    chars = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                  and any(isinstance(t, ast.Name) and t.id == 'CHARS' for t in n.targets)))
    assert len(chars) == 68 and chars[-3:] == ['I', 'O', '-']
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'LPRDataLoader')
    transform_node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'transform')
    scope = dict(np=np)
    exec(compile(ast.Module(body=[transform_node], type_ignores=[]), 'reviewed_loader_transform', 'exec'), scope)
    spec = importlib.util.spec_from_file_location('reviewed_lprnet', PUBLIC/'model/LPRNet.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    net = module.build_lprnet(lpr_max_len=7, phase=False, class_num=68, dropout_rate=0)
    net.load_state_dict(torch.load(PUBLIC/'weights/Final_LPRNet_model.pth', map_location='cpu', weights_only=True))
    net.eval()
    original_state = {k: v.clone() for k, v in net.state_dict().items()}
    gates = frozen_gates(manifest)
    write_json(OUT/'gates.json', gates)
    config = dict(input_hashes=hashes, classes=chars,
                  batch_size=1, device='cpu', torch_version=torch.__version__, opencv_version=cv2.__version__,
                  normalization='BGR float32: (pixel - 127.5) * 0.0078125; CHW',
                  variants=['original_cv2_linear', 'q8_bgr'], shape=[1, 3, 24, 94],
                  score='exp(log P(greedy sequence | all CTC paths) / 7); native blank=67',
                  threshold_fit='304 development identities only; apply identical threshold to subset76',
                  threshold_objective='maximize(correct, -wrong, -threshold) under wrong<=budget',
                  selection='legal7 candidates; max CTC score; ties lowest roi_index; no label access',
                  combined_gate='frozen native-crop learned blue class AND HS blue>yellow AND raw corner/box margins>=1',
                  integrity_limit='boundary gate only; does not prove complete character visibility',
                  pretrained_overlap='unknown; diagnostic only', new_training_steps=0,
                  source_image_reads=0, validation_image_reads=0, heldout_image_reads=0)
    write_json(OUT/'config.json', config)
    result = {}
    with torch.inference_mode():
        for variant in config['variants']:
            rows, logits_all, prepared = [], [], []
            for i, (r, im) in enumerate(zip(manifest, images)):
                resized = cv2.resize(im, (94, 24)) if variant == 'original_cv2_linear' else resize_q8(im, 24, 94)
                x = scope['transform'](None, resized)
                expected = ((resized.astype(np.float32)-127.5)*0.0078125).transpose(2, 0, 1)
                assert np.array_equal(x, expected)
                logits = net(torch.from_numpy(x[None].copy()))[0]
                assert logits.shape == (68, 18) and torch.isfinite(logits).all()
                rows.append(dict(roi_index=i, sample_index=r['sample_index'], candidate_index=r['candidate_index'],
                                 split=r['split'], label=r['source_transcript'], **decode(logits, chars)))
                logits_all.append(logits.numpy().copy())
                prepared.append(resized)
            np.savez_compressed(OUT/f'{variant}-logits.npz', logits=np.stack(logits_all))
            np.savez_compressed(OUT/f'{variant}-inputs.npz', bgr=np.stack(prepared))
            write_json(OUT/f'{variant}-roi-records.json', rows)
            grouped = defaultdict(list)
            for r in rows:
                grouped[r['sample_index']].append(r)
            variant_result = {}
            for gate_mode in ('ocr_only', 'combined'):
                selected = []
                for sample, proposals in grouped.items():
                    allowed = [r for r in proposals if r['legal'] and
                               (gate_mode == 'ocr_only' or gates[r['roi_index']]['combined_pass'])]
                    best = max(allowed, key=lambda r: (r['score'], -r['roi_index'])) if allowed else None
                    selected.append(dict(sample_index=sample, split=proposals[0]['split'], label=proposals[0]['label'],
                                         roi_index=best['roi_index'] if best else None,
                                         code=best['code'] if best else None, score=best['score'] if best else None))
                write_json(OUT/f'{variant}-{gate_mode}-selected.json', selected)
                variant_result[gate_mode] = dict(raw_legal_greedy_development=metrics(selected, 0),
                    raw_legal_greedy_tune=metrics([r for r in selected if r['split'] == 'tune'], 0),
                    max_wrong3=calibrate(selected, 3), zero_wrong=calibrate(selected, 0))
            # The first detector proposal gives an additional raw result with no grammar/confidence rejection.
            first = [p[0] for p in grouped.values()]
            variant_result['first_candidate_unfiltered_greedy'] = {
                name: dict(correct=sum(r['code'] == r['label'] for r in subset), total=len(subset))
                for name, subset in [('development', first), ('tune', [r for r in first if r['split'] == 'tune'])]}
            result[variant] = variant_result
            print(variant, variant_result, flush=True)
    assert all(torch.equal(original_state[k], v) for k, v in net.state_dict().items())
    assert hashes == {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in sources}
    result['audit'] = dict(model_state_unchanged=True, input_sources_unchanged=True,
                           gate_associations_verified=len(gates), combined_gate_pass=sum(g['combined_pass'] for g in gates),
                           elapsed_seconds=time.monotonic()-started)
    write_json(OUT/'results.json', result)
    artifacts = {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'frozen.json'}
    write_json(OUT/'frozen.json', dict(artifacts=artifacts, diagnostic_only=True))


if __name__ == '__main__':
    main()
