"""Fixed small development counterexample probe; no rule or threshold fitting."""
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import torch

import baseline as b
from compare_hyperlpr import ROOT, OUT, SOURCE, inspected_functions
from diagnose_bounded_candidates import FUNCTIONS, bounded
from diagnose_color_evidence import color_evidence
from geometry_sampler import sample_integer
from probe_hyperlpr_rejection import canvas720

sys.path.insert(0, str(ROOT/'tools/blue_plate/char_segment'))
from fixed_lprnet import FixedLPRNet, STRICT_THRESHOLD

DEST = OUT/'structure-partial-stroke-probe'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def main():
    DEST.mkdir(exist_ok=False)
    cv2.setNumThreads(2)
    torch.set_num_threads(4)
    freeze = OUT/'structure-development-v1/candidate-freeze.json'
    assert sha(freeze) == '7264ba12ad2b3f2f7fb205beff3dab223f5d2461f3c47a23e3f54365f9a86e79'
    dev = read(OUT/'structure-development-v1/records.json')
    originals = {r['sample_index']: r for r in read(OUT/'comparison-records.json') if r['split'] == 'development'}
    eligible = [r for r in dev if r['kind'] == 'positive' and r['selections']['strict/global_seven'] is not None]
    selected = sorted(eligible, key=lambda r:sha(ROOT/r['path']))[:8]
    regions = {'horizontal_middle20': [[0, .4], [1, .4], [1, .6], [0, .6]],
               'vertical_middle5': [[.475, 0], [.525, 0], [.525, 1], [.475, 1]]}
    sources = [Path(__file__), Path(b.__file__), freeze, ROOT/'tools/blue_plate/char_segment/fixed_lprnet.py',
               OUT/'structure-development-v1/records.json', OUT/'comparison-records.json',
               OUT/'y5fu_320x_sim.onnx', OUT/'litemodel_cls_96x_r1.onnx']
    hashes = {str(p): sha(p) for p in sources}
    write(DEST/'protocol-before-probe.json', dict(source_hashes=hashes,
        selected=[dict(sample_index=r['sample_index'], path=r['path'], sha256=sha(ROOT/r['path'])) for r in selected],
        selection='First 8 source SHA256 values among development positives accepted by frozen global/strict chain; no transcript selection.',
        regions=regions, color='whole native plate median BGR',
        scope='16 synthetic full-frame probes; not natural occlusion validation.',
        no_parameter_fitting=True, no_validation_or_heldout=True, threshold=STRICT_THRESHOLD,
        inference_inputs='edited frame only; no mask, edit metadata or reference text'))
    det = cv2.dnn.readNetFromONNX(str(OUT/'y5fu_320x_sim.onnx'))
    cls = cv2.dnn.readNetFromONNX(str(OUT/'litemodel_cls_96x_r1.onnx'))
    warp = inspected_functions(SOURCE/'common/tools_process.py', ['get_rotate_crop_image'])['get_rotate_crop_image']
    encode = inspected_functions(SOURCE/'inference/classification.py', ['encode_images'])['encode_images']
    recognizer = FixedLPRNet()
    logits_all = []

    def classify(image):
        cls.setInput(encode(cv2.resize(image, (96, 96)))[None])
        scores = cls.forward().reshape(-1)
        hs = color_evidence(image)
        return dict(color_class=int(scores.argmax()), scores=scores.tolist(), hs_pass=hs['hs_blue_over_yellow'],
                    blue_count=hs['counts']['blue_hs'], yellow_count=hs['counts']['yellow_hs'])

    def run_frame(frame):
        tensor, ratio, left, top = FUNCTIONS['detect_pre_precessing'](frame, (320, 320))
        det.setInput(tensor)
        result = bounded(det.forward(), ratio, left, top)
        proposals = []
        crops = []
        for i, p in enumerate(result['outputs']):
            if int(p[13]) != 0:
                continue
            raw = p[5:13].reshape(4, 2)
            points = raw.astype(int)
            fixed, _ = sample_integer(frame, points, 32, integer_solver=True)
            prediction = recognizer(fixed)
            logits = prediction.pop('logits')
            chars, mask, rects = b.segment(fixed, 'global', 'projection-char')
            corner_margin = float(min(raw[:, 0].min(), raw[:, 1].min(), 1279-raw[:, 0].max(), 719-raw[:, 1].max()))
            box_margin = float(min(p[0], p[1], 1279-p[2], 719-p[3]))
            native, fixed_color = classify(warp(frame, points)), classify(fixed)
            proposal = dict(candidate_index=i, points=points.tolist(), raw_points=raw.tolist(), box=p[:4].tolist(),
                detector_confidence=float(p[4]), corner_margin=corner_margin, box_margin=box_margin,
                ocr=prediction, global_seven=len(chars) == 7, measured_rects=[list(map(int, r)) for r in rects],
                native_color=native, fixed_color=fixed_color, logits_index=len(logits_all))
            for mode, color in [('native', native), ('fixed', fixed_color)]:
                proposal[mode+'_accepts'] = bool(prediction['strict_accepts'] and len(chars) == 7 and corner_margin >= 1
                    and box_margin >= 1 and color['color_class'] == 0 and color['hs_pass'])
            proposals.append(proposal)
            logits_all.append(logits)
            crops.append((fixed, mask))
        selections = {}
        for mode in ['native', 'fixed']:
            chosen = max((p for p in proposals if p[mode+'_accepts']), key=lambda p:(p['ocr']['score'], -p['candidate_index']), default=None)
            selections[mode] = None if chosen is None else dict(code=chosen['ocr']['code'], score=chosen['ocr']['score'], candidate_index=chosen['candidate_index'])
        return dict(detector_status=result['status'], outputs=proposals, selections=selections), crops

    rows = []
    for source in selected:
        original = originals[source['sample_index']]
        frame = canvas720(b.read_image(ROOT/source['path']))
        anchor = max(original['detector320'], key=lambda p:p['detector_confidence'])
        points = np.float32(anchor['points'])
        transform = cv2.getPerspectiveTransform(np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]), points)
        color = np.median(warp(frame, points.astype(int)).reshape(-1, 3), axis=0).astype(np.uint8)
        for kind, region in regions.items():
            polygon = np.rint(cv2.perspectiveTransform(np.float32([region]), transform)[0]).astype(np.int32)
            edited = frame.copy()
            cv2.fillConvexPoly(edited, polygon, tuple(map(int, color)))
            result, crops = run_frame(edited)
            stem = f'{source["sample_index"]}-{kind}'
            cv2.imwrite(str(DEST/f'{stem}.png'), edited)
            for p, (crop, mask) in zip(result['outputs'], crops):
                cv2.imwrite(str(DEST/f'{stem}-roi-{p["candidate_index"]}.png'), crop)
                cv2.imwrite(str(DEST/f'{stem}-roi-{p["candidate_index"]}-mask.png'), mask*255)
            rows.append(dict(id=stem, sample_index=source['sample_index'], path=source['path'], kind=kind,
                original_text_evaluation_only=source['label'], polygon=polygon.tolist(), fill_color=color.tolist(),
                modified_pixel_count=int(np.count_nonzero(np.any(edited != frame, axis=2))), result=result))
    assert hashes == {str(p): sha(p) for p in sources}
    write(DEST/'records.json', rows)
    np.savez_compressed(DEST/'logits.npz', logits=np.stack(logits_all))
    summary = {}
    for kind in regions:
        group = [r for r in rows if r['kind'] == kind]
        summary[kind] = dict(inputs=len(group),
            structure_pass_frames=sum(any(p['global_seven'] for p in r['result']['outputs']) for r in group),
            accepted={m:sum(r['result']['selections'][m] is not None for r in group) for m in ['native', 'fixed']},
            accepted_wrong_text={m:sum(r['result']['selections'][m] is not None and r['result']['selections'][m]['code'] != r['original_text_evaluation_only'] for r in group) for m in ['native', 'fixed']})
    write(DEST/'report.json', dict(summary=summary, frames=16, rois=len(logits_all), source_hashes_unchanged=True,
                                 rule_unchanged=True, threshold_unchanged=True, validation_or_heldout_evaluated=0))
    print(summary)


if __name__ == '__main__':
    main()
