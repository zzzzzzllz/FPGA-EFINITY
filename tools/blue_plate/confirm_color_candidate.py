"""Frozen HS candidate confirmation on 84 calibration images and 1164 edits.

Keeps the original reference unchanged. This is post-development calibration,
not independent blind testing. All crops and base inference use FrozenReference.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT, OUT
from diagnose_color_evidence import color_evidence
from hyperlpr_reference import FrozenReference
from probe_hyperlpr_fullframe import variants
from probe_hyperlpr_rejection import canvas720


def add_color_evidence(frame, result, warp):
    """Append candidate decisions without altering any original output field."""
    for p in result['outputs']:
        p['candidate_accepted'] = False
        if 'code' not in p:
            continue
        crop = warp(frame, np.array(p['points']))
        counts = color_evidence(crop)['counts']
        p['blue_count'], p['yellow_count'] = counts['blue_hs'], counts['yellow_hs']
        p['blue_evidence_pass'] = p['blue_count'] > p['yellow_count']
        p['candidate_accepted'] = p['accepted'] and p['blue_evidence_pass']
        p['candidate_rejection_reasons'] = p['rejection_reasons'] + ([] if p['blue_evidence_pass'] else ['blue_not_greater_than_yellow'])
    chosen = max((p for p in result['outputs'] if p['candidate_accepted']), key=lambda p:p['confidence'], default=None)
    result['candidate_selected'] = chosen
    result['candidate_accepted'] = chosen is not None
    return result


def extremes():
    def solid(h,s,v=200):
        return cv2.cvtColor(np.full((4,4,3), (h,s,v), dtype=np.uint8), cv2.COLOR_HSV2BGR)
    blue, yellow = solid(120,254), solid(25,254)
    equal = np.concatenate([blue[:,:2],yellow[:,:2]], axis=1)
    one = np.full_like(blue,128); one[0,0] = blue[0,0]
    cases = [('zero_blue_gray',solid(0,0),0,0,False), ('pure_yellow_s254',yellow,0,16,False),
        ('pure_blue_s255',solid(120,255),0,0,False), ('pure_blue_s254',blue,16,0,True),
        ('equal_blue_yellow',equal,8,8,False), ('one_blue_rest_gray',one,1,0,True)]
    rows=[]
    for name,image,nb,ny,expected in cases:
        ev=color_evidence(image)
        assert ev['counts']['blue_hs']==nb and ev['counts']['yellow_hs']==ny
        assert ev['hs_blue_over_yellow']==expected
        rows.append(dict(case=name,blue_count=nb,yellow_count=ny,pass_gate=expected))
    return rows


def main():
    out=OUT/'color-candidate-confirmation'
    out.mkdir(exist_ok=False)
    old_freeze=OUT/'real-rejection/reference-freeze.json'
    old=json.loads(old_freeze.read_text())
    for path,digest in old['source_hashes'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
    inputs=OUT/'fullframe-rejection/records.json'
    sources=[Path(__file__),Path('tools/blue_plate/diagnose_color_evidence.py'),Path('tools/blue_plate/baseline.py'),
        Path('tools/blue_plate/probe_hyperlpr_fullframe.py'),inputs,old_freeze]
    protocol=dict(candidate_id='hs-blue-over-yellow-v1',
        rule='OpenCV uint8 BGR2HSV, blue 100<H<140, yellow 15<H<40, shared 95<S<255. No V condition. Accept only blue_count>yellow_count, AND all original gates.',
        sampling='Same native perspective crop as original recognition/color classifier, before their separate resize.',
        scope='84 calibration positives plus all 388x3 original edited frames. Post-development confirmation, not blind evaluation.',
        tuning=False,heldout_read=0,original_reference_unchanged=True,
        source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        original_dependencies=old['source_hashes'], models=old['models'])
    (out/'candidate-freeze.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    (out/'extremes.json').write_text(json.dumps(extremes(),indent=2),encoding='utf8')
    ref=FrozenReference()
    rows=json.loads(inputs.read_text(encoding='utf8'))
    previous={(r['sample_index'],r['kind']):r for r in rows}
    original=json.loads((OUT/'comparison-records.json').read_text(encoding='utf8'))
    records=[];changes=[]
    for source in original:
        assert source['split'] in ['development','validation']
        frame=canvas720(b.read_image(ROOT/source['path']))
        anchor=max(source['detector320'],key=lambda p:p['detector_confidence'])
        for kind,edited,intervention in variants(frame,np.array(anchor['points']),ref.warp):
            if kind=='positive' and source['split']!='validation':continue
            result=add_color_evidence(edited,ref.run_frame(edited),ref.warp)
            prior=previous[(source['sample_index'],kind)]
            eligible=[p for p in prior['outputs'] if p.get('grammar_color_p90_box_corners_inside') and min(p['emission_scores'])>=.8]
            expected=max(eligible,key=lambda p:p['confidence'],default=None)
            old_code=result['selected']['code'] if result['selected'] else None
            new_code=result['candidate_selected']['code'] if result['candidate_selected'] else None
            assert old_code==(expected['code'] if expected else None)
            assert result['accepted']==bool(eligible)
            assert [(p['points'],p['code'],p['confidence']) for p in result['outputs'] if 'code' in p]==[(p['points'],p['code'],p['confidence']) for p in prior['outputs'] if 'code' in p]
            row=dict(sample_index=source['sample_index'],split=source['split'],kind=kind,source=source['path'],
                original_reference_text=source['label'],old_code=old_code,new_code=new_code,changed=old_code!=new_code,result=result)
            records.append(row)
            if row['changed']:
                changes.append(row)
                cv2.imwrite(str(out/f'changed-{source["sample_index"]}-{kind}.png'),edited)
            if len(records)%100==0:print(f'{len(records)}/1248 frames',flush=True)
    summary={}
    for kind in sorted({r['kind'] for r in records}):
        for split in ['development','validation']:
            subset=[r for r in records if r['kind']==kind and r['split']==split]
            if not subset:continue
            summary[kind+'/'+split]=dict(total=len(subset),changed=sum(r['changed'] for r in subset),methods={})
            for method in ['old_code','new_code']:
                accepted=sum(r[method] is not None for r in subset)
                metrics=dict(accepted=accepted,rejected=len(subset)-accepted)
                if kind=='positive':metrics.update(correct=sum(r[method]==r['original_reference_text'] for r in subset),wrong=sum(r[method] is not None and r[method]!=r['original_reference_text'] for r in subset))
                summary[kind+'/'+split]['methods'][method]=metrics
    assert len(records)==1248
    (out/'records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'changes.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'report.json').write_text(json.dumps(dict(protocol=protocol,base_replay_exact=True,summary=summary),ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
