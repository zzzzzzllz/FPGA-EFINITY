"""Evaluate explicit 32 pre-NMS / 2 single-line post-NMS overflow rejection.

These are experimental computation limits, not upstream defaults. No truncation.
All below-limit sorting, suppression and coordinates use the inspected upstream.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT,OUT,SOURCE,inspected_functions
from diagnose_color_evidence import color_evidence
from probe_hyperlpr_fullframe import variants
from probe_hyperlpr_rejection import canvas720

FUNCTIONS=inspected_functions(SOURCE/'inference/multitask_detect.py',
    ['xywh2xyxy','nms','restore_box','detect_pre_precessing','post_precessing','letter_box'])


def bounded(raw,ratio,left,top):
    if raw.shape!=(1,6300,15):raise ValueError('Expected fixed 6300x15 detector output')
    count=int(np.count_nonzero(raw[:,:,4]>.25))
    if count>32:
        return dict(status='threshold_candidate_overflow',pre_nms=count,post_nms=None,single_line=None,outputs=np.empty((0,14),np.float32))
    outputs=FUNCTIONS['post_precessing'](raw.copy(),ratio,left,top)
    singles=int(np.count_nonzero(outputs[:,13]==0))
    status='single_line_candidate_overflow' if singles>2 else 'ok'
    return dict(status=status,pre_nms=count,post_nms=len(outputs),single_line=singles,
        outputs=outputs if status=='ok' else np.empty((0,14),np.float32))


def synthetic_checks():
    def make(n,singles,overlap=False,tied=False):
        raw=np.zeros((1,6300,15),np.float32)
        for i in range(n):
            x,y=(40,40) if overlap else (20+(i%8)*35,20+(i//8)*35)
            raw[0,i,:5]=[x,y,20,12,.9 if tied else .95-i*.001]
            raw[0,i,5:13]=[x-10+i*.001,y-6,x+10,y-6,x+10,y+6,x-10,y+6]
            raw[0,i,13:15]=[.9,.1] if i<singles else [.1,.9]
        return raw
    cases=[]
    for n in [31,32,33]:cases.append((f'pre_{n}_overlapping',make(n,n,True), 'ok' if n<=32 else 'threshold_candidate_overflow'))
    for n in [1,2,3]:cases.append((f'post_single_{n}',make(n,n),'ok' if n<=2 else 'single_line_candidate_overflow'))
    cases += [('two_single_thirty_double',make(32,2),'ok'),('three_single_one_double',make(4,3),'single_line_candidate_overflow'),
        ('thirty_two_double',make(32,0),'ok'),('tied_two_single_thirty_double',make(32,2,tied=True),'ok'),
        ('tied_overlapping',make(32,32,True,True),'ok'),('no_candidates',make(0,0),'ok')]
    threshold=make(2,2);threshold[0,0,4]=.25;threshold[0,1,4]=np.nextafter(np.float32(.25),np.float32(1))
    cases.append(('strict_objectness_boundary',threshold,'ok'))
    # Higher-scoring double-line proposal suppresses overlapping single-line
    # proposals in original cross-class NMS. Do not filter double lines first.
    mixed=make(4,3,True);mixed[0,3,4]=.99
    cases.append(('double_suppresses_single',mixed,'ok'))
    results=[]
    for name,raw,expected in cases:
        original=FUNCTIONS['post_precessing'](raw.copy(),1.,0,0)
        result=bounded(raw,1.,0,0)
        assert result['status']==expected
        if expected=='ok':assert np.array_equal(result['outputs'],original)
        else:assert len(result['outputs'])==0
        # Mapping returned landmarks to source rows records actual tie order.
        survivors=[]
        for p in original:
            matches=np.flatnonzero(np.all(raw[0,:,5:13]==p[5:13],axis=1))
            assert len(matches)==1;survivors.append(int(matches[0]))
        results.append(dict(case=name,status=result['status'],pre_nms=result['pre_nms'],post_nms=result['post_nms'],single_line=result['single_line'],
            original_survivor_indices=survivors,returned=len(result['outputs']),below_limit_exact=result['status']=='ok'))
    assert next(r for r in results if r['case']=='strict_objectness_boundary')['pre_nms']==1
    assert next(r for r in results if r['case']=='double_suppresses_single')['single_line']==0
    return results


def main():
    cv2.setNumThreads(2)
    out=OUT/'bounded-candidate-diagnostic';out.mkdir(exist_ok=False)
    model=OUT/'y5fu_320x_sim.onnx';net=cv2.dnn.readNetFromONNX(str(model))
    warp=inspected_functions(SOURCE/'common/tools_process.py',['get_rotate_crop_image'])['get_rotate_crop_image']
    protocol=dict(scope='Experimental fail-closed 32/2 limits; original reference unchanged. Frames only, no patch inputs.',
        pre_nms_limit=32,post_nms_single_limit=2,truncation=False,scan_predictions=6300,
        numpy=np.__version__,opencv=cv2.__version__,heldout_read=0,
        source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),model,SOURCE/'inference/multitask_detect.py',OUT/'color-candidate-confirmation/candidate-freeze.json']})
    (out/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    (out/'synthetic.json').write_text(json.dumps(synthetic_checks(),indent=2),encoding='utf8')
    old_rows=json.loads((OUT/'fullframe-rejection/records.json').read_text(encoding='utf8'))
    old={(r['sample_index'],r['kind']):r for r in old_rows}
    colors={(r['sample_index'],r['kind']):r for r in json.loads((OUT/'color-sampling-comparison/records.json').read_text(encoding='utf8'))}
    records=[]
    def evaluate(image,reference_outputs,old_code,metadata):
        tensor,ratio,left,top=FUNCTIONS['detect_pre_precessing'](image,(320,320))
        net.setInput(tensor);raw=net.forward()
        all_post=FUNCTIONS['post_precessing'](raw.copy(),ratio,left,top)
        singles=all_post[all_post[:,13]==0]
        scored=[p for p in reference_outputs if 'code' in p]
        assert len(singles)==len(scored)
        for p,expected in zip(singles,scored):
            assert p[5:13].reshape(4,2).astype(int).tolist()==expected['points']
            assert float(p[4])==expected['detector_confidence']
        result=bounded(raw,ratio,left,top)
        if result['status']=='ok':assert np.array_equal(result['outputs'],all_post)
        selected=old_code if result['status']=='ok' else None
        eligible=raw[raw[:,:,4]>.25]
        scores=(eligible[:,13:15]*eligible[:,4:5]).max(axis=1)
        record=dict(**metadata,pre_nms=result['pre_nms'],original_post_nms=len(all_post),original_single_line=len(singles),
            status=result['status'],old_code=old_code,new_code=selected,changed=old_code!=selected,
            equal_combined_score_duplicates=len(scores)-len(np.unique(scores)))
        records.append(record)
        if len(records)%100==0:print(f'{len(records)}/1563 full frames',flush=True)
    for original in json.loads((OUT/'comparison-records.json').read_text(encoding='utf8')):
        assert original['split'] in ['development','validation']
        image=canvas720(b.read_image(ROOT/original['path']))
        anchor=max(original['detector320'],key=lambda p:p['detector_confidence'])
        for kind,frame,intervention in variants(image,np.array(anchor['points']),warp):
            key=(original['sample_index'],kind);selected=colors[key]['selections']['native']
            evaluate(frame,old[key]['outputs'],selected['code'] if selected else None,
                dict(sample_index=original['sample_index'],split=original['split'],kind=kind,source=original['path'],label=original['label'] if kind=='positive' else None))
    for folder in ['easypr-evaluation','opencv-evaluation','failure-source-evaluation']:
        for row in json.loads((OUT/'real-rejection'/folder/'records.json').read_text(encoding='utf8')):
            if row['input_kind']!='frame':continue
            frame=canvas720(b.read_image(ROOT/row['path']))
            eligible=[p for p in row['result']['outputs'] if p['accepted'] and color_evidence(warp(frame,np.array(p['points'])))['hs_blue_over_yellow']]
            chosen=max(eligible,key=lambda p:p['confidence'],default=None)
            evaluate(frame,row['result']['outputs'],chosen['code'] if chosen else None,
                dict(sample_id=row['id'],split='seen_real_diagnostic',kind='real_'+row['manual_label'],source=row['path'],label=None))
    summary={}
    for kind in sorted({r['kind'] for r in records}):
        group=[r for r in records if r['kind']==kind]
        summary[kind]=dict(frames=len(group),statuses=dict(Counter(r['status'] for r in group)),
            maximum_pre_nms=max(r['pre_nms'] for r in group),maximum_post_nms_single=max(r['original_single_line'] for r in group),
            changed=sum(r['changed'] for r in group),old_accepted=sum(r['old_code'] is not None for r in group),new_accepted=sum(r['new_code'] is not None for r in group),
            correct_losses=sum(r['label'] is not None and r['old_code']==r['label'] and r['new_code']!=r['label'] for r in group),
            newly_accepted=sum(r['old_code'] is None and r['new_code'] is not None for r in group))
    (out/'records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'changes.json').write_text(json.dumps([r for r in records if r['changed'] or r['status']!='ok'],ensure_ascii=False,indent=2),encoding='utf8')
    report=dict(protocol=protocol,synthetic_cases=14,real_frame_count=len(records),summary=summary,
        equal_score_frames=sum(r['equal_combined_score_duplicates']>0 for r in records),below_limit_post_nms_exact=True)
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
