"""Frozen offline reference: 320 detector, native RGB crop, blue and score gates.

One pipeline for future diagnostic sets. Thresholds are not configurable by data.
Patch scoring is exposed only as an explicitly separate downstream diagnostic.
"""
import ast
import hashlib

import cv2
import numpy as np

from compare_hyperlpr import SOURCE, OUT, grammar, inspected_functions
from probe_hyperlpr_rejection import canvas720


MODEL_HASHES = {
    'y5fu_320x_sim.onnx': '2a985dc63a5cc947ec36d18503d6fc0fd54525b9dba17f2fe29a71e86b44456d',
    'rpv3_mdict_160_r3.onnx': '8fb08b5db2adeccf43b05006bbbf409e4659d08d72e46a62631c00ff751eaeb3',
    'litemodel_cls_96x_r1.onnx': 'fe123688d3bf08b9ef029fcd57f3ac4644ac2e5ef8b9e7a676aacd5fad152142',
}


class FrozenReference:
    def __init__(self):
        cv2.setNumThreads(2)
        for name, expected in MODEL_HASHES.items():
            if hashlib.sha256((OUT/name).read_bytes()).hexdigest() != expected:
                raise ValueError(f'Frozen model changed: {name}')
        self.det, self.rec, self.cls = [cv2.dnn.readNetFromONNX(str(OUT/name)) for name in MODEL_HASHES]
        self.encode = inspected_functions(SOURCE/'inference/recognition.py', ['encode_images'])['encode_images']
        self.cls_encode = inspected_functions(SOURCE/'inference/classification.py', ['encode_images'])['encode_images']
        self.warp = inspected_functions(SOURCE/'common/tools_process.py', ['get_rotate_crop_image'])['get_rotate_crop_image']
        self.detect = inspected_functions(SOURCE/'inference/multitask_detect.py', ['xywh2xyxy', 'nms', 'restore_box',
            'detect_pre_precessing', 'post_precessing', 'letter_box'])
        self.token = ast.literal_eval(ast.parse((SOURCE/'common/tokenize.py').read_text(encoding='utf8')).body[0].value)

    def score_patch(self, crop):
        if crop is None or crop.ndim != 3 or min(crop.shape[:2]) < 1:
            raise ValueError('Expected nonempty BGR crop')
        self.rec.setInput(self.encode(crop, crop.shape[1]/crop.shape[0], (48, 160))[None])
        probability = self.rec.forward()[0]
        indices = probability.argmax(axis=1)
        kept = [i for i, idx in enumerate(indices) if idx and (i == 0 or idx != indices[i-1])]
        known = bool(np.all(indices < len(self.token)))
        code = ''.join(self.token[indices[i]] for i in kept) if known else ''
        scores = [float(probability[i, indices[i]]) for i in kept]
        mean = float(np.mean(scores)) if known and scores else 0.
        weakest = min(scores) if known and scores else 0.
        self.cls.setInput(self.cls_encode(cv2.resize(crop, (96, 96)))[None])
        colors = self.cls.forward().reshape(-1)
        color = int(colors.argmax())
        reasons = []
        if not known: reasons.append('unmapped_token')
        if not grammar(code): reasons.append('not_ordinary_seven_characters')
        if color != 0: reasons.append('not_blue_class')
        if mean < .9: reasons.append('mean_below_0.9')
        if weakest < .8: reasons.append('min_character_below_0.8')
        return dict(code=code, confidence=mean, min_character=weakest, emission_scores=scores,
            color_class=color, color_scores=colors.tolist(), downstream_accepted=not reasons,
            rejection_reasons=reasons)

    def run_frame(self, frame):
        if frame.shape != (720, 1280, 3):
            raise ValueError('Reference detector frame must be 1280x720 BGR')
        tensor, ratio, left, top = self.detect['detect_pre_precessing'](frame, (320, 320))
        self.det.setInput(tensor)
        proposals = self.detect['post_precessing'](self.det.forward(), ratio, left, top)
        outputs = []
        for p in proposals:
            raw = p[5:13].reshape(4, 2)
            points = raw.astype(int)
            entry = dict(points=points.tolist(), raw_points=raw.tolist(), box=p[:4].tolist(),
                detector_confidence=float(p[4]), accepted=False)
            if int(p[13]) != 0:
                entry['rejection_reasons'] = ['double_line']
                outputs.append(entry)
                continue
            if min(max(np.linalg.norm(points[0]-points[1]), np.linalg.norm(points[2]-points[3])),
                   max(np.linalg.norm(points[0]-points[3]), np.linalg.norm(points[1]-points[2]))) < 1:
                entry['rejection_reasons'] = ['degenerate_corners']
                outputs.append(entry)
                continue
            corner_margin = float(min(raw[:, 0].min(), raw[:, 1].min(), 1279-raw[:, 0].max(), 719-raw[:, 1].max()))
            box_margin = float(min(p[0], p[1], 1279-p[2], 719-p[3]))
            # Keep counterfactual crop scores for review; boundary rejection is
            # decided on raw coordinates, regardless of BORDER_REPLICATE output.
            entry.update(self.score_patch(self.warp(frame, points)))
            entry.update(corner_margin=corner_margin, box_margin=box_margin)
            if corner_margin < 1: entry['rejection_reasons'].append('corners_touch_frame')
            if box_margin < 1: entry['rejection_reasons'].append('box_touches_frame')
            entry['accepted'] = not entry['rejection_reasons']
            outputs.append(entry)
        selected = max((p for p in outputs if p['accepted']), key=lambda p:p['confidence'], default=None)
        return dict(proposal_count=len(proposals), outputs=outputs, selected=selected,
                    accepted=selected is not None, rejection_reason=None if selected else 'all_candidates_rejected' if outputs else 'no_detection')

    def run_image(self, image):
        return self.run_frame(canvas720(image))
