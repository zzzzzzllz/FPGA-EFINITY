"""Check whether the verified fixed-size integer sampler preserves CNN results."""
import ast
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT, SOURCE, OUT, inspected_functions, grammar, summarize
from geometry_sampler import sample_integer


def main():
    cv2.setNumThreads(2)
    previous = OUT/'comparison-records.json'
    original = json.loads(previous.read_text(encoding='utf8'))
    encode = inspected_functions(SOURCE/'inference/recognition.py', ['encode_images'])['encode_images']
    token = ast.literal_eval(ast.parse((SOURCE/'common/tokenize.py').read_text(encoding='utf8')).body[0].value)
    model = OUT/'rpv3_mdict_160_r3.onnx'
    net = cv2.dnn.readNetFromONNX(str(model))
    def recognize(plate):
        net.setInput(encode(plate, plate.shape[1]/plate.shape[0], (48,160))[None])
        probability = net.forward()[0]
        indices = probability.argmax(axis=1)
        if np.any(indices >= len(token)):
            return dict(code='', confidence=0., grammar=False, reason='unmapped_model_class_77')
        kept = [i for i, idx in enumerate(indices) if idx and (i == 0 or idx != indices[i-1])]
        code = ''.join(token[indices[i]] for i in kept)
        return dict(code=code, confidence=float(np.mean([probability[i,indices[i]] for i in kept])) if kept else 0.,
                    grammar=grammar(code))
    rows = []
    for original_row in original:
        if original_row['split'] == 'heldout':
            raise AssertionError('Heldout input is forbidden')
        image = b.read_image(ROOT/original_row['path'])
        h,w = image.shape[:2]
        scale = min(1280/w,720/h)
        nw,nh = round(w*scale),round(h*scale)
        dx,dy = (1280-nw)//2,(720-nh)//2
        padded = np.zeros((720,1280,3),np.uint8)
        padded[dy:dy+nh,dx:dx+nw] = cv2.resize(image,(nw,nh),interpolation=cv2.INTER_AREA)
        row = {k:original_row[k] for k in ['sample_index','path','split','label']}
        row['fixed_opencv'] = []; row['fixed_integer'] = []
        for candidate in original_row['detector320']:
            if candidate.get('reason') == 'double_line':
                continue
            points = candidate['points']
            row['fixed_opencv'].append(recognize(b.warp(padded,points)))
            plate, _ = sample_integer(padded,points,32,integer_solver=True)
            row['fixed_integer'].append(recognize(plate))
        rows.append(row)
        if len(rows)%100 == 0:
            print(f'Checked sampler variants {len(rows)}/388',flush=True)
    files = [Path(__file__), ROOT/'tools/blue_plate/geometry_sampler.py',
             ROOT/'tools/blue_plate/compare_hyperlpr.py', previous, model]
    report = dict(images=len(rows), heldout_evaluated=0,
                  metrics={mode:summarize(rows,mode) for mode in ['fixed_opencv','fixed_integer']},
                  source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    (OUT/'sampling-records.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'sampling-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report['metrics'],ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
