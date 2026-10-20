"""Re-infer frozen 388 inputs to count threshold survivors before NMS.

Original records contain post-NMS proposals only. Verify those remain identical;
do not infer missing pre-NMS counts from them or impose a candidate cap.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT,OUT,SOURCE,inspected_functions
from probe_hyperlpr_rejection import canvas720


def main():
    cv2.setNumThreads(2)
    out=OUT/'detector-candidate-counts';out.mkdir(exist_ok=False)
    source=OUT/'comparison-records.json';model=OUT/'y5fu_320x_sim.onnx'
    net=cv2.dnn.readNetFromONNX(str(model))
    funcs=inspected_functions(SOURCE/'inference/multitask_detect.py',['xywh2xyxy','nms','restore_box','detect_pre_precessing','post_precessing','letter_box'])
    records=[]
    for row in json.loads(source.read_text(encoding='utf8')):
        assert row['split'] in ['development','validation']
        frame=canvas720(b.read_image(ROOT/row['path']))
        tensor,ratio,left,top=funcs['detect_pre_precessing'](frame,(320,320))
        net.setInput(tensor);raw=net.forward()
        assert raw.shape==(1,6300,15)
        eligible=raw[raw[:,:,4]>.25]
        post=funcs['post_precessing'](raw.copy(),ratio,left,top)
        assert len(post)==len(row['detector320'])
        for p,old in zip(post,row['detector320']):
            assert p[5:13].reshape(4,2).astype(int).tolist()==old['points']
            assert float(p[4])==old['detector_confidence']
        records.append(dict(sample_index=row['sample_index'],split=row['split'],path=row['path'],
            raw_predictions=6300,objectness_gt_025=len(eligible),single_class_before_nms=int(np.sum(eligible[:,13:15].argmax(axis=1)==0)),
            post_nms=len(post),post_nms_single=int(np.sum(post[:,13]==0))))
        if len(records)%100==0:print(f'Counted {len(records)}/388 images',flush=True)
    summary={}
    for split in ['development','validation','all']:
        group=[r for r in records if split=='all' or r['split']==split]
        summary[split]={}
        for key in ['objectness_gt_025','post_nms']:
            values=np.array([r[key] for r in group])
            summary[split][key]=dict(images=len(group),total=int(values.sum()),minimum=int(values.min()),maximum=int(values.max()),
                percentiles={str(p):float(np.percentile(values,p)) for p in [50,90,95,99]},
                histogram=dict(sorted(Counter(map(int,values)).items())),maximum_sample_indices=[r['sample_index'] for r in group if r[key]==int(values.max())])
    report=dict(scope='388 frozen non-heldout positive scenes only; not a general maximum.',heldout_read=0,
        threshold='Raw objectness strictly >0.25. Upstream NMS IoU=0.5; ranking uses class probability*objectness.',
        candidate_truncation=False,post_nms_exact_match=True,summary=summary,
        source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),source,model,SOURCE/'inference/multitask_detect.py']})
    (out/'records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
