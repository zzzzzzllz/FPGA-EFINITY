"""Re-detect uniformly edited full frames; diagnostic, not G1 acceptance.

Frozen detector corners define interventions only. Every edited frame is detected
again. Original text is an evaluation reference, never a label for partial input.
"""
import ast
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT, SOURCE, OUT, inspected_functions, grammar
from probe_hyperlpr_rejection import canvas720


def variants(image, points, warp):
    """Integer translations preserve pixel scale; zero-pad the opposite edge."""
    left = points[[0, 3]].mean(axis=0)
    right = points[[1, 2]].mean(axis=0)
    cut_left = int(np.ceil((left * .8 + right * .2)[0]))
    cut_right = int(np.floor((left * .2 + right * .8)[0]))
    assert 0 < cut_left < cut_right < image.shape[1]
    yield 'positive', image, dict(dx=0)
    shifted = np.zeros_like(image)
    shifted[:, :image.shape[1]-cut_left] = image[:, cut_left:]
    yield 'left20_frame_edge', shifted, dict(dx=-cut_left, cut_x=cut_left)
    shifted = np.zeros_like(image)
    shifted[:, image.shape[1]-cut_right:] = image[:, :cut_right]
    yield 'right20_frame_edge', shifted, dict(dx=image.shape[1]-cut_right, cut_x=cut_right)
    unit = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
    matrix = cv2.getPerspectiveTransform(unit, points.astype(np.float32))
    strip = np.float32([[[.4, 0], [.6, 0], [.6, 1], [.4, 1]]])
    polygon = np.rint(cv2.perspectiveTransform(strip, matrix)[0]).astype(np.int32)
    color = np.median(warp(image, points).reshape(-1, 3), axis=0).astype(np.uint8)
    occluded = image.copy()
    cv2.fillConvexPoly(occluded, polygon, tuple(map(int, color)))
    yield 'middle20_fullframe_occlusion', occluded, dict(polygon=polygon.tolist(), color=color.tolist())


def main():
    cv2.setNumThreads(2)
    out = OUT/'fullframe-rejection'
    out.mkdir(exist_ok=False)
    models = [OUT/name for name in ['y5fu_320x_sim.onnx', 'rpv3_mdict_160_r3.onnx', 'litemodel_cls_96x_r1.onnx']]
    det, rec, cls = [cv2.dnn.readNetFromONNX(str(p)) for p in models]
    encode = inspected_functions(SOURCE/'inference/recognition.py', ['encode_images'])['encode_images']
    cls_encode = inspected_functions(SOURCE/'inference/classification.py', ['encode_images'])['encode_images']
    warp = inspected_functions(SOURCE/'common/tools_process.py', ['get_rotate_crop_image'])['get_rotate_crop_image']
    detect = inspected_functions(SOURCE/'inference/multitask_detect.py', ['xywh2xyxy', 'nms', 'restore_box',
                                'detect_pre_precessing', 'post_precessing', 'letter_box'])
    token = ast.literal_eval(ast.parse((SOURCE/'common/tokenize.py').read_text(encoding='utf8')).body[0].value)
    source = OUT/'comparison-records.json'
    originals = json.loads(source.read_text(encoding='utf8'))
    protocol = dict(scope='Synthetic full-frame diagnostic; correlated sources, unknown pretraining overlap.',
        inputs=len(originals), heldout_images_read=0, selection='all single-line proposals; frame accepted if any pass',
        intervention='Highest original detector confidence corners; left/right cuts at 20/80 percent of midline x, integer translate to frame edge without resizing, opposite side zero-padded; middle strip projected into full frame.',
        gates=['grammar_color', 'grammar_color_p90', 'grammar_color_p90_corners_inside', 'grammar_color_p90_box_corners_inside'],
        thresholds=dict(recognition_mean=.9, inside_margin_pixels=1),
        training_policy='Only development failures may enter future reject training after review. No transcript labels for edited inputs. Validation evaluation only.',
        source_hashes={str(p.relative_to(ROOT)).replace('\\', '/'):hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in [Path(__file__), source, *models]})
    (out/'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf8')
    records = []
    started = time.perf_counter()
    for original in originals:
        assert original['split'] in ['development', 'validation']
        image = canvas720(b.read_image(ROOT/original['path']))
        anchor = max(original['detector320'], key=lambda p:p['detector_confidence'])
        for kind, frame, intervention in variants(image, np.array(anchor['points']), warp):
            tensor, ratio, left, top = detect['detect_pre_precessing'](frame, (320, 320))
            det.setInput(tensor)
            proposals = detect['post_precessing'](det.forward(), ratio, left, top)
            outputs = []
            for p in proposals:
                if int(p[13]) != 0:
                    continue
                points = p[5:13].reshape(4, 2).astype(int)
                if min(max(np.linalg.norm(points[0]-points[1]), np.linalg.norm(points[2]-points[3])),
                       max(np.linalg.norm(points[0]-points[3]), np.linalg.norm(points[1]-points[2]))) < 1:
                    outputs.append(dict(reason='degenerate_corners'))
                    continue
                crop = warp(frame, points)
                rec.setInput(encode(crop, crop.shape[1]/crop.shape[0], (48, 160))[None])
                probability = rec.forward()[0]
                indices = probability.argmax(axis=1)
                kept = [i for i, idx in enumerate(indices) if idx and (i == 0 or idx != indices[i-1])]
                known = bool(np.all(indices < len(token)))
                code = ''.join(token[indices[i]] for i in kept) if known else ''
                scores = [float(probability[i, indices[i]]) for i in kept]
                confidence = float(np.mean(scores)) if scores and known else 0.
                cls.setInput(cls_encode(cv2.resize(crop, (96, 96)))[None])
                color = int(cls.forward().reshape(-1).argmax())
                # Raw float coordinates are checked before the sampler truncates them.
                raw = p[5:13].reshape(4, 2)
                corner_margin = float(min(raw[:, 0].min(), raw[:, 1].min(),
                                          1279-raw[:, 0].max(), 719-raw[:, 1].max()))
                box_margin = float(min(p[0], p[1], 1279-p[2], 719-p[3]))
                valid = grammar(code) and color == 0
                gates = dict(grammar_color=valid, grammar_color_p90=valid and confidence >= .9,
                    grammar_color_p90_corners_inside=valid and confidence >= .9 and corner_margin >= 1,
                    grammar_color_p90_box_corners_inside=valid and confidence >= .9 and min(corner_margin, box_margin) >= 1)
                entry = dict(code=code, confidence=confidence, emission_scores=scores, color_class=color,
                    points=points.tolist(), raw_points=raw.tolist(), box=p[:4].tolist(),
                    detector_confidence=float(p[4]), corner_margin=corner_margin, box_margin=box_margin, **gates)
                outputs.append(entry)
                if kind != 'positive' and valid:
                    name = f'{kind}-{original["sample_index"]:04}-{len(outputs):02}'
                    cv2.imwrite(str(out/f'{name}-crop.png'), crop)
            gates = {key:any(p.get(key, False) for p in outputs) for key in protocol['gates']}
            row = dict(sample_index=original['sample_index'], split=original['split'], source=original['path'],
                original_reference_text=original['label'], kind=kind, intervention=intervention,
                anchor_points=anchor['points'], proposals=len(proposals), outputs=outputs, **gates)
            if kind != 'positive' and gates['grammar_color']:
                path = out/f'{kind}-{original["sample_index"]:04}-frame.png'
                cv2.imwrite(str(path), frame)
                row['failure_frame'] = str(path.relative_to(ROOT)).replace('\\', '/')
                row['training_text_label'] = None
                row['training_usage'] = 'reject_candidate_requires_review' if original['split'] == 'development' else 'evaluation_only'
            records.append(row)
        if len(records) % 100 == 0:
            print(f'{len(records)}/1552 frames, {time.perf_counter()-started:.1f}s', flush=True)
    summary = {}
    for kind in sorted({r['kind'] for r in records}):
        summary[kind] = {}
        for split in ['development', 'validation']:
            rows = [r for r in records if r['kind'] == kind and r['split'] == split]
            summary[kind][split] = dict(total=len(rows), detected=sum(r['proposals'] > 0 for r in rows),
                **{key:sum(r[key] for r in rows) for key in protocol['gates']})
            if kind == 'positive':
                for key in protocol['gates']:
                    selected = [max((p for p in r['outputs'] if p.get(key, False)), key=lambda p:p['confidence'], default=None) for r in rows]
                    summary[kind][split][key+'_correct'] = sum(p is not None and p['code'] == r['original_reference_text'] for r,p in zip(rows,selected))
    (out/'records.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf8')
    report = dict(**protocol, seconds=time.perf_counter()-started, summary=summary)
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
