"""Prepare existing diagnostic frames/patches for frozen LPRNet inference.

Rerun detection and both color-CNN inputs. Never import prior OCR acceptance.
"""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT, OUT, SOURCE, inspected_functions
from diagnose_bounded_candidates import FUNCTIONS, bounded
from diagnose_color_evidence import color_evidence
from geometry_sampler import sample_integer
from probe_hyperlpr_fullframe import variants
from probe_hyperlpr_rejection import canvas720

DEST = OUT/'lpr-rejection'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def main():
    cv2.setNumThreads(2)
    DEST.mkdir(exist_ok=False)
    models = {'y5fu_320x_sim.onnx': '2a985dc63a5cc947ec36d18503d6fc0fd54525b9dba17f2fe29a71e86b44456d',
              'litemodel_cls_96x_r1.onnx': 'fe123688d3bf08b9ef029fcd57f3ac4644ac2e5ef8b9e7a676aacd5fad152142'}
    for name, digest in models.items():
        assert sha(OUT/name) == digest
    manifests = [OUT/'real-rejection'/p for p in ['input-manifest.json', 'failure-source-manifest.json', 'opencv/input-manifest.json']]
    originals_path = OUT/'comparison-records.json'
    sources = [Path(__file__), Path('tools/blue_plate/geometry_sampler.py'),
               Path('tools/blue_plate/diagnose_bounded_candidates.py'), Path('tools/blue_plate/diagnose_color_evidence.py'),
               Path('tools/blue_plate/probe_hyperlpr_fullframe.py'), originals_path, *manifests,
               SOURCE/'inference/multitask_detect.py', SOURCE/'inference/classification.py', SOURCE/'common/tools_process.py']
    hashes = {str(p): sha(p) for p in sources}
    write(DEST/'preparation-freeze.json', dict(source_hashes=hashes, models=models, heldout_read=0,
        scope='1164 existing edits plus 107 real diagnostic inputs; 96 patches remain downstream-only.',
        geometry='Existing integer Q32/Q5 224x64 BGR. Patches use their four outer pixel corners, without frame detection/boundary claims.',
        color='Rerun learned classifier independently on native crop ->96 and fixed224x64 ->96, both original cv2 linear resize/encode. HS counts on both inputs.',
        old_ocr_gates_used=False, threshold_fit=False,
        thresholds={'strict': 0.9931710550839266, 'comparison': 0.9386077887914179}))
    det = cv2.dnn.readNetFromONNX(str(OUT/'y5fu_320x_sim.onnx'))
    cls = cv2.dnn.readNetFromONNX(str(OUT/'litemodel_cls_96x_r1.onnx'))
    warp = inspected_functions(SOURCE/'common/tools_process.py', ['get_rotate_crop_image'])['get_rotate_crop_image']
    encode = inspected_functions(SOURCE/'inference/classification.py', ['encode_images'])['encode_images']
    records, rois = [], []

    def score_color(im):
        cls.setInput(encode(cv2.resize(im, (96, 96)))[None])
        scores = cls.forward().reshape(-1)
        ev = color_evidence(im)
        return dict(color_class=int(scores.argmax()), scores=scores.tolist(),
                    blue_count=ev['counts']['blue_hs'], yellow_count=ev['counts']['yellow_hs'],
                    hs_pass=ev['hs_blue_over_yellow'])

    def add_crop(image, points, native, entry):
        fixed, matrix = sample_integer(image, points, 32, integer_solver=True)
        entry.update(roi_index=len(rois), inverse_q32=matrix.tolist(),
                     bgr_sha256=hashlib.sha256(fixed.tobytes()).hexdigest(),
                     native_color=score_color(native), fixed_color=score_color(fixed))
        rois.append(fixed)

    def evaluate(image, metadata):
        outputs = []
        if metadata['input_kind'] == 'patch':
            h, w = image.shape[:2]
            points = np.array([[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]])
            entry = dict(candidate_index=0, points=points.tolist(), boundary_pass=None)
            add_crop(image, points, image, entry)
            outputs.append(entry)
            status = 'downstream_patch'
            pre = None
        else:
            assert image.shape == (720, 1280, 3)
            tensor, ratio, left, top = FUNCTIONS['detect_pre_precessing'](image, (320, 320))
            det.setInput(tensor)
            raw = det.forward()
            result = bounded(raw, ratio, left, top)
            status, pre = result['status'], result['pre_nms']
            for i, p in enumerate(result['outputs']):
                entry = dict(candidate_index=i, detector_confidence=float(p[4]), detector_class=int(p[13]))
                outputs.append(entry)
                if int(p[13]) != 0:
                    entry['skip_reason'] = 'double_line'
                    continue
                raw_points = p[5:13].reshape(4, 2)
                points = raw_points.astype(int)
                corner_margin = float(min(raw_points[:, 0].min(), raw_points[:, 1].min(),
                                          1279-raw_points[:, 0].max(), 719-raw_points[:, 1].max()))
                box_margin = float(min(p[0], p[1], 1279-p[2], 719-p[3]))
                entry.update(points=points.tolist(), raw_points=raw_points.tolist(), box=p[:4].tolist(),
                             corner_margin=corner_margin, box_margin=box_margin,
                             boundary_pass=corner_margin >= 1 and box_margin >= 1)
                add_crop(image, points, warp(image, points), entry)
        records.append(dict(**metadata, detector_status=status, pre_nms=pre,
                            frame_pixels_sha256=hashlib.sha256(image.tobytes()).hexdigest(), outputs=outputs))
        if len(records) % 100 == 0:
            print(f'prepared {len(records)}/1271 inputs; {len(rois)} ROIs', flush=True)

    for original in json.loads(originals_path.read_text(encoding='utf8')):
        assert original['split'] in ['development', 'validation']
        frame = canvas720(b.read_image(ROOT/original['path']))
        anchor = max(original['detector320'], key=lambda p:p['detector_confidence'])
        for kind, image, intervention in variants(frame, np.array(anchor['points']), warp):
            if kind == 'positive':
                continue
            evaluate(image, dict(id=f'{original["sample_index"]}-{kind}', sample_index=original['sample_index'],
                                split=original['split'], input_kind='frame', kind=kind, path=original['path'],
                                source_sha256=sha(ROOT/original['path']), intervention=intervention,
                                expected_output='reject'))
    for manifest in manifests:
        for item in json.loads(manifest.read_text(encoding='utf8'))['items']:
            assert sha(ROOT/item['path']) == item['sha256']
            image = b.read_image(ROOT/item['path'])
            if item['input_kind'] == 'frame':
                image = canvas720(image)
            evaluate(image, dict(**item, kind='real_'+item['manual_label'], split='seen_real_diagnostic'))
    assert len(records) == 1271 and sum(r['input_kind'] == 'patch' for r in records) == 96
    assert hashes == {str(p): sha(p) for p in sources}
    write(DEST/'prepared-records.json', records)
    np.savez_compressed(DEST/'prepared-rois.npz', bgr=np.stack(rois))
    write(DEST/'preparation-summary.json', dict(inputs=len(records), rois=len(rois),
        input_kind_counts={k: sum(r['input_kind'] == k for r in records) for k in ['patch', 'frame']},
        artifacts={p.name: sha(p) for p in [DEST/'prepared-records.json', DEST/'prepared-rois.npz']}))
    print(f'Prepared {len(records)} inputs, {len(rois)} ROIs', flush=True)


if __name__ == '__main__':
    main()
