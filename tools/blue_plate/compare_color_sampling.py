"""Isolate HS color sampling: native cubic versus actual integer Q32/Q5 RGB.

No new recognition or classification inference. All non-color decisions and
candidate ordering scores come from immutable full-frame records.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT, OUT, SOURCE, inspected_functions
from diagnose_color_evidence import color_evidence
from geometry_sampler import sample_integer
from probe_hyperlpr_fullframe import variants
from probe_hyperlpr_rejection import canvas720


def main():
    cv2.setNumThreads(2)
    out=OUT/'color-sampling-comparison'
    out.mkdir(exist_ok=False)
    previous=OUT/'fullframe-rejection/records.json'
    originals=OUT/'comparison-records.json'
    freeze=OUT/'color-candidate-confirmation/candidate-freeze.json'
    frozen=json.loads(freeze.read_text())
    for group in ['source_hashes','original_dependencies']:
        for path,digest in frozen[group].items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
    sources=[Path(__file__),Path('tools/blue_plate/geometry_sampler.py'),previous,originals,freeze]
    protocol=dict(scope='Sampling-only comparison, all 388 non-heldout positives and their 1164 original edited frames.',
        heldout_read=0,tuning=False,frozen_non_color_fields=['points','code','confidence','emission_scores','color_class','grammar','boundary gates'],
        native='Original variable-size INTER_CUBIC / BORDER_REPLICATE crop.',
        fixed='Existing sample_integer(...,32,integer_solver=True): Q16 corners, Q32 coefficients, Q5 coordinates, 224x64 bilinear RGB, zero outside, half-up pixel rounding.',
        color_rule='Frozen strict HS blue count > yellow count; all original .9/.8/class/grammar/boundary gates unchanged.',
        source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (out/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    warp=inspected_functions(SOURCE/'common/tools_process.py',['get_rotate_crop_image'])['get_rotate_crop_image']
    old={(r['sample_index'],r['kind']):r for r in json.loads(previous.read_text(encoding='utf8'))}
    records=[];changed_candidates=[];changed_frames=[];errors=[]
    for original in json.loads(originals.read_text(encoding='utf8')):
        assert original['split'] in ['development','validation']
        frame=canvas720(b.read_image(ROOT/original['path']))
        anchor=max(original['detector320'],key=lambda p:p['detector_confidence'])
        for kind,image,intervention in variants(frame,np.array(anchor['points']),warp):
            previous_row=old[(original['sample_index'],kind)]
            outputs=[]
            for index,p in enumerate(previous_row['outputs']):
                if 'code' not in p:continue
                points=p['points']
                native=warp(image,np.array(points))
                nc=color_evidence(native)['counts']
                base=bool(p.get('grammar_color_p90_box_corners_inside') and min(p['emission_scores'])>=.8)
                native_pass=nc['blue_hs']>nc['yellow_hs']
                entry=dict(candidate_index=index,points=points,code=p['code'],confidence=p['confidence'],
                    emission_scores=p['emission_scores'],color_class=p['color_class'],base_accepted=base,
                    native_shape=list(native.shape),native_blue=nc['blue_hs'],native_yellow=nc['yellow_hs'],
                    native_color_pass=native_pass,native_accepted=base and native_pass)
                try:
                    fixed,matrix=sample_integer(image,points,32,integer_solver=True)
                except ValueError as exc:
                    entry.update(sampling_error=str(exc),fixed_color_pass=False,fixed_accepted=False)
                    errors.append(dict(sample_index=original['sample_index'],kind=kind,**entry))
                else:
                    assert fixed.shape==(64,224,3) and fixed.dtype==np.uint8
                    assert np.all(matrix>=-(1<<47)) and np.all(matrix<(1<<47))
                    fc=color_evidence(fixed)['counts'];fixed_pass=fc['blue_hs']>fc['yellow_hs']
                    entry.update(fixed_blue=fc['blue_hs'],fixed_yellow=fc['yellow_hs'],fixed_color_pass=fixed_pass,
                        fixed_accepted=base and fixed_pass,matrix_q32=matrix.tolist())
                    if native_pass!=fixed_pass:
                        changed=dict(sample_index=original['sample_index'],split=original['split'],kind=kind,**entry)
                        changed_candidates.append(changed)
                        stem=f'{original["sample_index"]}-{kind}-{index}'
                        cv2.imwrite(str(out/f'{stem}-native.png'),native)
                        cv2.imwrite(str(out/f'{stem}-fixed.png'),fixed)
                outputs.append(entry)
            selections={}
            for mode in ['native','fixed']:
                selected=max((p for p in outputs if p[mode+'_accepted']),key=lambda p:p['confidence'],default=None)
                selections[mode]=None if selected is None else dict(candidate_index=selected['candidate_index'],code=selected['code'],confidence=selected['confidence'])
            row=dict(sample_index=original['sample_index'],split=original['split'],kind=kind,source=original['path'],
                original_reference_text=original['label'],outputs=outputs,selections=selections,
                selection_changed=selections['native']!=selections['fixed'])
            records.append(row)
            if row['selection_changed']:changed_frames.append(row)
        if len(records)%200==0:print(f'{len(records)}/1552 frames sampled',flush=True)
    summary={}
    for kind in sorted({r['kind'] for r in records}):
        for split in ['development','validation']:
            group=[r for r in records if r['kind']==kind and r['split']==split]
            summary[kind+'/'+split]=dict(frames=len(group),candidates=sum(len(r['outputs']) for r in group),
                color_pass_changes=sum(p['native_color_pass']!=p['fixed_color_pass'] for r in group for p in r['outputs']),
                selection_changes=sum(r['selection_changed'] for r in group),methods={})
            for mode in ['native','fixed']:
                accepted=sum(r['selections'][mode] is not None for r in group)
                metrics=dict(accepted=accepted,rejected=len(group)-accepted)
                if kind=='positive':metrics.update(correct=sum(r['selections'][mode] is not None and r['selections'][mode]['code']==r['original_reference_text'] for r in group),wrong=sum(r['selections'][mode] is not None and r['selections'][mode]['code']!=r['original_reference_text'] for r in group))
                summary[kind+'/'+split]['methods'][mode]=metrics
    for name,data in [('records',records),('changed-candidates',changed_candidates),('changed-frames',changed_frames),('sampling-errors',errors)]:
        (out/f'{name}.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    report=dict(protocol=protocol,summary=summary,sampling_errors=len(errors),color_changed_candidates=len(changed_candidates),changed_frames=len(changed_frames))
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
