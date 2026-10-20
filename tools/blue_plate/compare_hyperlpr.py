"""Diagnostic HyperLPR3 comparison on the existing 388 non-heldout images.

Runs inspected preprocessing functions, not package initialization/download code.
Pretrained model training overlap is unknown: these results are not G1 acceptance.
"""
import ast
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np

import baseline as b

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'tmp/blue-plate-review/mature-research/hyperlpr/Prj-Python/hyperlpr3'
OUT = ROOT/'tmp/blue-plate-normal-g1/mature-detector'


def inspected_functions(path, names):
    tree = ast.parse(path.read_text(encoding='utf8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes} != set(names):
        raise ValueError(f'Missing inspected function in {path}')
    scope = dict(np=np, cv2=cv2, copy=copy, math=math)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
    return scope


def grammar(code):
    return (len(code) == 7 and code[0] in b.PROVINCES and code[1] in b.LETTERS and
            all(c in b.ADS for c in code[2:]))


def model_cost(net, shape):
    ids, inputs, outputs = net.getLayersShapes(shape)
    layers = []
    for layer_id, inp, output in zip(ids, inputs, outputs):
        layer = net.getLayer(int(layer_id))
        row = dict(name=layer.name, type=layer.type, inputs=[x.tolist() for x in inp],
                   outputs=[x.tolist() for x in output], blobs=[list(x.shape) for x in layer.blobs])
        if layer.type == 'Convolution':
            # Weight shape already contains Cin/groups. OpenCV getFLOPS ignores
            # this reduction for depthwise layers, so do not use total FLOPS/2.
            row['macs'] = int(layer.blobs[0].size*np.prod(output[0][2:])*output[0][0])
        layers.append(row)
    weights, activations = net.getMemoryConsumption(shape)
    return dict(shape=list(shape), convolution_macs=sum(x.get('macs', 0) for x in layers),
                opencv_loaded_weight_bytes=weights, opencv_sum_blob_bytes=activations,
                opencv_reported_flops_not_group_corrected=net.getFLOPS(shape),
                layer_types=dict(Counter(x['type'] for x in layers)), layers=layers)


def summarize(records, mode):
    result = {}
    for split in ['development', 'validation']:
        subset = [r for r in records if r['split'] == split]
        result[split] = {}
        for threshold in [0, .8, .9, .95, .98, .99]:
            counts = dict(total=len(subset), correct=0, wrong=0, reject=0)
            for row in subset:
                valid = [p for p in row[mode] if p['grammar'] and p['confidence'] >= threshold]
                selected = max(valid, key=lambda p:p['confidence']) if valid else None
                key = 'reject' if selected is None else 'correct' if selected['code'] == row['label'] else 'wrong'
                counts[key] += 1
            result[split][str(threshold)] = counts
    return result


def main():
    cv2.setNumThreads(2)
    det_source = SOURCE/'inference/multitask_detect.py'
    rec_source = SOURCE/'inference/recognition.py'
    warp_source = SOURCE/'common/tools_process.py'
    token_source = SOURCE/'common/tokenize.py'
    det_functions = inspected_functions(det_source, ['xywh2xyxy', 'nms', 'restore_box',
        'detect_pre_precessing', 'post_precessing', 'letter_box'])
    encode = inspected_functions(rec_source, ['encode_images'])['encode_images']
    warp = inspected_functions(warp_source, ['get_rotate_crop_image'])['get_rotate_crop_image']
    token_tree = ast.parse(token_source.read_text(encoding='utf8'))
    token = ast.literal_eval(next(n.value for n in token_tree.body if isinstance(n, ast.Assign)))
    rec_model = OUT/'rpv3_mdict_160_r3.onnx'
    rec_net = cv2.dnn.readNetFromONNX(str(rec_model))
    detectors = {size:cv2.dnn.readNetFromONNX(str(OUT/f'y5fu_{size}x_sim.onnx')) for size in [320, 640]}
    costs = {'recognizer':model_cost(rec_net, (1,3,48,160))}
    costs.update({f'detector{size}':model_cost(net, (1,3,size,size)) for size, net in detectors.items()})
    (OUT/'model-costs.json').write_text(json.dumps(costs, indent=2), encoding='utf8')
    def recognize(plate):
        tensor = encode(plate, plate.shape[1]/plate.shape[0], (48,160))[None]
        rec_net.setInput(tensor)
        probabilities = rec_net.forward()[0]
        if probabilities.shape[1] != len(token)+1:
            raise ValueError('Tokenizer/model class mismatch')
        indices = probabilities.argmax(axis=1)
        if np.any(indices >= len(token)):
            return dict(code='', confidence=0.0, grammar=False, reason='unmapped_model_class_77',
                        raw_indices=indices.tolist())
        keep = [i for i, idx in enumerate(indices) if idx != 0 and (i == 0 or idx != indices[i-1])]
        code = ''.join(token[indices[i]] for i in keep)
        confidence = float(np.mean([probabilities[i, indices[i]] for i in keep])) if keep else 0.0
        return dict(code=code, confidence=confidence, grammar=grammar(code))
    frozen = ROOT/'tmp/blue-plate-normal-g1/integer-geometry-solver'
    manifest_path = ROOT/'tmp/blue-plate-normal-g1/full-dual-local-geometry/samples.json'
    samples = json.loads(manifest_path.read_text(encoding='utf8'))
    candidates_path = frozen/'candidates.json'
    candidates = json.loads(candidates_path.read_text(encoding='utf8'))
    plates_path = frozen/'candidate-plates.npz'
    plates = np.load(plates_path)['rgb_bgr']
    by_sample = {}
    for index, candidate in enumerate(candidates):
        by_sample.setdefault(candidate['sample_index'], []).append(index)
    records = []
    start = time.perf_counter()
    for sample_index, sample in enumerate(samples):
        if sample['split'] == 'heldout':
            continue
        source = b.read_image(ROOT/sample['path'])
        h, w = source.shape[:2]
        scale = min(1280/w,720/h)
        nw, nh = round(w*scale), round(h*scale)
        dx, dy = (1280-nw)//2, (720-nh)//2
        image = np.zeros((720,1280,3), np.uint8)
        image[dy:dy+nh,dx:dx+nw] = cv2.resize(source,(nw,nh),interpolation=cv2.INTER_AREA)
        row = dict(sample_index=sample_index, path=sample['path'], split=sample['split'], label=sample['label'])
        row['current_roi'] = [dict(candidate_index=index, **recognize(plates[index])) for index in by_sample.get(sample_index, [])]
        for size, net in detectors.items():
            tensor, ratio, left, top = det_functions['detect_pre_precessing'](image, (size,size))
            net.setInput(tensor)
            prediction = net.forward()
            # Preserve the published helper's actual defaults: objectness>.25,
            # IoU .5; constructor threshold fields are not passed by _postprocess.
            proposals = det_functions['post_precessing'](prediction, ratio, left, top)
            entries = []
            for proposal in proposals:
                points = proposal[5:13].reshape(4,2).astype(int)
                if int(proposal[13]) != 0:
                    entries.append(dict(code='', confidence=0., grammar=False, reason='double_line',
                                        points=points.tolist(), detector_confidence=float(proposal[4])))
                    continue
                plate = warp(image, points)
                entries.append(dict(**recognize(plate), points=points.tolist(), box=proposal[:4].tolist(),
                                    detector_confidence=float(proposal[4])))
            row[f'detector{size}'] = entries
        records.append(row)
        if len(records) % 25 == 0:
            print(f'Compared {len(records)}/388 images in {time.perf_counter()-start:.1f}s', flush=True)
    files = [Path(__file__), det_source, rec_source, warp_source, token_source, manifest_path, candidates_path,
             plates_path, rec_model, *[OUT/f'y5fu_{size}x_sim.onnx' for size in detectors]]
    hashes = {str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    report = dict(opencv=cv2.__version__, images=len(records), heldout_evaluated=0,
                  pretrained_training_overlap='unknown; diagnostic comparison, not acceptance',
                  tokenizer_mismatch='Published table has 77 entries; model has 78 outputs. Class 77 argmax explicitly rejected, never relabeled.',
                  selection='highest recognizer mean confidence among grammar-valid single-line predictions',
                  source_hashes=hashes, seconds=time.perf_counter()-start,
                  metrics={mode:summarize(records, mode) for mode in ['current_roi','detector320','detector640']})
    (OUT/'comparison-records.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf8')
    (OUT/'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report['metrics'],ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
