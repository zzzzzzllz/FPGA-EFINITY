"""Development diagnostic after observed yellow failures; no frozen-rule edit.

EasyPR colorMatch/plateColorJudge constants come from pinned core_func.cpp.
The HS dominance candidate is an explicit simplification, not upstream behavior.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT, OUT
from hyperlpr_reference import FrozenReference
from probe_hyperlpr_rejection import canvas720


def color_evidence(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hue, sat = hsv[..., 0], hsv[..., 1]
    value = cv2.equalizeHist(hsv[..., 2])
    counts = {}
    for name, lo, hi in [('blue', 100, 140), ('yellow', 15, 40)]:
        hue_ok = (hue > lo) & (hue < hi)
        counts[name+'_hs'] = int(np.count_nonzero(hue_ok & (sat > 95) & (sat < 255)))
        for adaptive in [False, True]:
            # Upstream divides integer bounds before converting to float:
            # yellow half-width is 12, center is 27 (not 12.5 / 27.5).
            half = np.float32((hi-lo)//2)
            center = np.float32(lo)+half
            distance = np.abs(hue.astype(np.float32)-center)/half
            minimum = np.float32(64)-np.float32(32)*(np.float32(1)-distance) if adaptive else 95
            mask = hue_ok & (sat > minimum) & (sat < 255) & (value > minimum) & (value < 255)
            counts[name+('_adaptive' if adaptive else '_fixed')] = int(np.count_nonzero(mask))
    area = image.shape[0]*image.shape[1]
    fraction = lambda count: float(np.float32(count)/np.float32(area))
    return dict(area=area, counts=counts,
        easypr_fixed=fraction(counts['blue_fixed']) > float(np.float32(.45)),
        easypr_adaptive=fraction(counts['blue_adaptive']) > float(np.float32(.45)),
        hs_blue_over_yellow=counts['blue_hs'] > counts['yellow_hs'])


def self_check():
    # Scalar source-order predicate catches bounds, strictness, integer yellow
    # half-width, and adaptive minimum differences in the vectorized port.
    image = np.random.default_rng(20261018).integers(0, 256, (39, 137, 3), dtype=np.uint8)
    evidence = color_evidence(image)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hsv[..., 2] = cv2.equalizeHist(hsv[..., 2])
    for name, lo, hi in [('blue', 100, 140), ('yellow', 15, 40)]:
        for adaptive in [False, True]:
            count = 0
            for h,s,v in hsv.reshape(-1, 3):
                h,s,v = int(h),int(s),int(v)
                half = np.float32((hi-lo)//2)
                distance = np.float32(abs(h-(lo+half)))/half
                minimum = np.float32(64)-np.float32(32)*(np.float32(1)-distance) if adaptive else 95
                count += lo < h < hi and minimum < s < 255 and minimum < v < 255
            assert count == evidence['counts'][name+('_adaptive' if adaptive else '_fixed')]


def main():
    self_check()
    out = OUT/'color-evidence-development'
    out.mkdir(exist_ok=False)
    rules = ['easypr_fixed', 'easypr_adaptive', 'hs_blue_over_yellow']
    protocol = dict(scope='Development diagnostic proposed after real yellow failures; not independent acceptance.',
        rules=dict(easypr_fixed='EasyPR colorMatch nonadaptive + plateColorJudge blue fraction >0.45',
            easypr_adaptive='EasyPR colorMatch adaptive + plateColorJudge blue fraction >0.45',
            hs_blue_over_yellow='Adaptation: same strict H bounds and 95<S<255, omit equalized V; accept only blue pixel count > yellow pixel count.'),
        tuning='No fitting or sweep; source constants and three candidate rules frozen before this run.',
        forbidden_upstream_fallback='getPlateType defaults unknown to BLUE; intentionally not used.',
        validation_inputs=0, heldout_inputs=0, original_reference_unchanged=True,
        source_sha256=hashlib.sha256((OUT/'easypr-judge/src/core/core_func.cpp').read_bytes()).hexdigest(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out/'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf8')
    ref = FrozenReference()
    records = []
    def candidate(crop, old):
        ev = color_evidence(crop)
        return dict(**old, color_evidence=ev, color_gate_accepts={key:bool(old['accepted'] and ev[key]) for key in rules})
    # Original full-frame positive decisions are reconstructed from frozen
    # candidates, never reranked using transcript labels.
    original = json.loads((OUT/'fullframe-rejection/records.json').read_text(encoding='utf8'))
    dev = [r for r in original if r['kind']=='positive' and r['split']=='development']
    proposals = {r['sample_index']:r for r in json.loads((OUT/'comparison-records.json').read_text(encoding='utf8'))}
    for row in dev:
        frame = canvas720(b.read_image(ROOT/row['source']))
        outputs = []
        for p in row['outputs']:
            accepted = bool(p.get('grammar_color_p90_box_corners_inside') and min(p['emission_scores']) >= .8)
            crop = ref.warp(frame, np.array(p['points']))
            outputs.append(candidate(crop, dict(code=p['code'], confidence=p['confidence'], accepted=accepted)))
        records.append(dict(kind='development_positive_frame', sample_index=row['sample_index'], label=row['original_reference_text'], outputs=outputs))
        anchor = max(proposals[row['sample_index']]['detector320'], key=lambda p:p['detector_confidence'])
        crop = ref.warp(frame, np.array(anchor['points']))
        for name, hue in [('synthetic_green_patch', 60), ('synthetic_yellow_patch', 30)]:
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            hsv[..., 0][hsv[..., 1] > 60] = hue
            edited = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
            score = ref.score_patch(edited)
            records.append(dict(kind=name, sample_index=row['sample_index'], outputs=[candidate(edited,
                dict(code=score['code'], confidence=score['confidence'], accepted=score['downstream_accepted']))]))
        if len(records)%150 == 0: print(f'{len(records)}/912 positive/recolored records', flush=True)
    # Already seen real diagnoses are not relabeled as an independent test set.
    for folder in ['easypr-evaluation', 'opencv-evaluation', 'failure-source-evaluation']:
        source_rows = json.loads((OUT/'real-rejection'/folder/'records.json').read_text(encoding='utf8'))
        for row in source_rows:
            image = b.read_image(ROOT/row['path'])
            if row['input_kind']=='patch':
                p = row['result']
                outputs = [candidate(image, dict(code=p['code'], confidence=p['confidence'], accepted=p['accepted']))]
            else:
                frame = canvas720(image)
                outputs = [candidate(ref.warp(frame, np.array(p['points'])),
                    dict(code=p['code'], confidence=p['confidence'], accepted=p['accepted']))
                    for p in row['result']['outputs'] if 'code' in p]
            records.append(dict(kind='real_'+row['input_kind']+'_'+row['manual_label'], sample_id=row['id'], source=row['path'], outputs=outputs))
    summary = {}
    for kind in sorted({r['kind'] for r in records}):
        group = [r for r in records if r['kind']==kind]
        summary[kind] = dict(total=len(group), methods={})
        for method in ['frozen_reference', *rules]:
            correct=wrong=accepted=0
            for row in group:
                valid = [p for p in row['outputs'] if p['accepted'] if method=='frozen_reference' or p['color_gate_accepts'][method]]
                selected = max(valid, key=lambda p:p['confidence'], default=None)
                accepted += selected is not None
                if 'label' in row and selected:
                    correct += selected['code']==row['label']
                    wrong += selected['code']!=row['label']
            summary[kind]['methods'][method] = dict(accepted=accepted, rejected=len(group)-accepted,
                correct=correct, wrong=wrong, additional_rejections=summary[kind]['methods'].get('frozen_reference',{}).get('accepted',accepted)-accepted)
    (out/'records.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf8')
    (out/'report.json').write_text(json.dumps(dict(protocol=protocol, summary=summary), ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
