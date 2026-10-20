"""Audit error groups and prepare split-preserving candidate training metadata.

Geometry eligibility is a review flag, not proof of complete characters or a
negative label. Evaluation always retains every image and candidate.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'tmp/blue-plate-normal-g1/mature-detector'


def selected(row, mode, threshold=0):
    valid = [x for x in row[mode] if x['grammar'] and x['confidence'] >= threshold]
    return max(valid, key=lambda x:x['confidence']) if valid else None


def outcome(row, prediction):
    return 'reject' if prediction is None else 'correct' if prediction['code'] == row['label'] else 'wrong'


def main():
    base_path = ROOT/'tmp/blue-plate-normal-g1/full-dual-local-geometry/results.json'
    sample_path = base_path.with_name('samples.json')
    candidate_path = ROOT/'tmp/blue-plate-normal-g1/integer-geometry-solver/candidates.json'
    comparison_path = OUT/'comparison-records.json'
    base = {r['path']:r for r in json.loads(base_path.read_text(encoding='utf8')) if r['mode']=='automatic'}
    samples = json.loads(sample_path.read_text(encoding='utf8'))
    candidates = json.loads(candidate_path.read_text(encoding='utf8'))
    rows = json.loads(comparison_path.read_text(encoding='utf8'))
    groups = {}
    calibrated = {}
    for mode in ['current_roi','detector320','detector640']:
        development = [r for r in rows if r['split']=='development']
        thresholds = sorted({0., *[np.nextafter(p['confidence'], float('inf')) for r in development
                                  for p in [selected(r,mode)] if p]})
        choices = []
        for threshold in thresholds:
            counts = Counter(outcome(r,selected(r,mode,threshold)) for r in development)
            if counts['wrong']<=3:
                choices.append((-counts['correct'],threshold))
        threshold = min(choices)[1]
        calibrated[mode] = dict(threshold=float(threshold),
            rule='maximize development correct subject to <=3 wrong, then smallest threshold',
            counts={split:dict(Counter(outcome(r,selected(r,mode,threshold)) for r in rows if r['split']==split))
                    for split in ['development','validation']})
    for row in rows:
        old = base[row['path']]['result']
        if old['status']=='scored':
            if all(x['accepted'] for x in old['scores']):
                group = 'baseline_correct' if old['raw']==row['label'] else 'baseline_wrong'
            else:
                group = 'classifier_reject'
        else:
            group = old['status']
        target = groups.setdefault(group,{mode:Counter() for mode in ['current_roi','detector320','detector640']})
        for mode in target:
            target[mode][outcome(row,selected(row,mode))] += 1
    geometry = {}
    candidate_records = []
    for index,candidate in enumerate(candidates):
        sample_index = candidate['sample_index']
        sample = samples[sample_index]
        if sample['split']=='heldout':
            raise AssertionError('Heldout candidate found')
        if sample_index not in geometry:
            image = b.read_image(ROOT/sample['path'])
            h,w = image.shape[:2]
            scale = min(1280/w,720/h)
            nw,nh = round(w*scale),round(h*scale)
            points = np.float32(sample['points'])*[nw/w,nh/h]+[(1280-nw)//2,(720-nh)//2]
            geometry[sample_index] = cv2.convexHull(np.float32(points))
        truth = geometry[sample_index]
        quad = cv2.convexHull(np.float32(candidate['points']))
        intersection,_ = cv2.intersectConvexConvex(truth,quad)
        truth_area,area = cv2.contourArea(truth),cv2.contourArea(quad)
        coverage = float(intersection/truth_area)
        iou = float(intersection/(truth_area+area-intersection))
        flag = ('fulltext_geometry_review' if coverage>=.98 and iou>=.5 else
                'partial_or_misaligned_review' if intersection>0 else 'unverified_background_review')
        candidate_records.append(dict(candidate_index=index,sample_index=sample_index,
            path=sample['path'],split=sample['split'],source_transcript=sample['label'],
            transcript_authorized_for_training=False,review_flag=flag,quad_iou=iou,
            annotated_quad_coverage=coverage,points=candidate['points'],
            usage='training_review' if sample['split']=='development' else 'evaluation_only'))
    split_counts = {split:dict(Counter(r['review_flag'] for r in candidate_records if r['split']==split))
                    for split in ['development','validation']}
    provinces = {split:dict(Counter(s['label'][0] for s in samples if s['split']==split))
                 for split in ['development','validation']}
    manifest = dict(policy='All candidates retained. Geometry flags require review. No automatic full-text label on partial crops; no unverified crop is a certified negative. Validation is evaluation-only; heldout images never loaded.',
                    records=candidate_records)
    files = [Path(__file__),base_path,sample_path,candidate_path,comparison_path]
    report = dict(raw_error_groups=groups,development_calibrated=calibrated,
                  candidate_geometry_counts=split_counts,province_counts=provinces,heldout_images_read=0,
                  source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    (OUT/'candidate-training-review.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'failure-groups.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_hashes'},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
