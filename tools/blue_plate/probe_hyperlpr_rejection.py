"""Blue-type/completeness stress diagnostics, with no heldout or model tuning.

Partial and recolored ROIs are synthetic. Above-plate scene crops are correlated
and not certified negative scenes. Preserve every accepted case for review.
"""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT, SOURCE, OUT, inspected_functions, grammar, model_cost
from blue_mask_integer import blue_hs


def canvas720(source):
    h,w = source.shape[:2]
    scale = min(1280/w,720/h)
    nw,nh = round(w*scale),round(h*scale)
    dx,dy = (1280-nw)//2,(720-nh)//2
    image = np.zeros((720,1280,3),np.uint8)
    image[dy:dy+nh,dx:dx+nw] = cv2.resize(source,(nw,nh),interpolation=cv2.INTER_AREA)
    return image


def main():
    cv2.setNumThreads(2)
    out = OUT/'rejection-probe'
    out.mkdir(exist_ok=True)
    rec_file = OUT/'rpv3_mdict_160_r3.onnx'
    cls_file = OUT/'litemodel_cls_96x_r1.onnx'
    det_file = OUT/'y5fu_320x_sim.onnx'
    rec,cls,det = [cv2.dnn.readNetFromONNX(str(p)) for p in [rec_file,cls_file,det_file]]
    (out/'color-model-cost.json').write_text(json.dumps(model_cost(cls,(1,3,96,96)),indent=2),encoding='utf8')
    encode = inspected_functions(SOURCE/'inference/recognition.py',['encode_images'])['encode_images']
    cls_encode = inspected_functions(SOURCE/'inference/classification.py',['encode_images'])['encode_images']
    warp = inspected_functions(SOURCE/'common/tools_process.py',['get_rotate_crop_image'])['get_rotate_crop_image']
    detect = inspected_functions(SOURCE/'inference/multitask_detect.py',['xywh2xyxy','nms','restore_box',
                                'detect_pre_precessing','post_precessing','letter_box'])
    token = ast.literal_eval(ast.parse((SOURCE/'common/tokenize.py').read_text(encoding='utf8')).body[0].value)
    records = []
    def score(crop):
        rec.setInput(encode(crop,crop.shape[1]/crop.shape[0],(48,160))[None])
        probability = rec.forward()[0]
        indices = probability.argmax(axis=1)
        if np.any(indices>=len(token)):
            code='';confidence=0.;reason='unmapped_model_class_77'
        else:
            kept = [i for i,idx in enumerate(indices) if idx and (i==0 or idx!=indices[i-1])]
            code = ''.join(token[indices[i]] for i in kept)
            confidence = float(np.mean([probability[i,indices[i]] for i in kept])) if kept else 0.
            reason = 'scored'
        cls.setInput(cls_encode(cv2.resize(crop,(96,96)))[None])
        types = cls.forward().reshape(-1)
        return dict(code=code,confidence=confidence,grammar=grammar(code),reason=reason,
                    color_class=int(types.argmax()),color_scores=types.tolist(),hs_coverage=float(blue_hs(crop).mean()))
    def record(crop,kind,index,split,path,label=''):
        row=dict(kind=kind,sample_index=index,source_split=split,source=path,label=label,**score(crop))
        row['accepted_grammar'] = row['grammar']
        row['accepted_color'] = row['grammar'] and row['color_class']==0
        row['accepted_color_p90'] = row['accepted_color'] and row['confidence']>=.9
        row['accepted_hs25'] = row['grammar'] and row['hs_coverage']>=.25
        records.append(row)
        if kind!='positive' and row['accepted_color']:
            cv2.imwrite(str(out/f'{kind}-{index:04}-{len(records):04}.png'),crop)
    comparison = OUT/'comparison-records.json'
    originals = json.loads(comparison.read_text(encoding='utf8'))
    for row in originals:
        if row['split']=='heldout':raise AssertionError('Heldout input')
        image=canvas720(b.read_image(ROOT/row['path']))
        # Uniform selection uses detector confidence, never annotation/transcript.
        proposal=max(row['detector320'],key=lambda x:x['detector_confidence'])
        crop=warp(image,np.array(proposal['points']))
        w=crop.shape[1]
        variants={'positive':crop,'left20_removed':crop[:,int(np.ceil(.2*w)):],
                  'right20_removed':crop[:,:int(np.floor(.8*w))]}
        occluded=crop.copy();background=np.median(crop.reshape(-1,3),axis=0).astype(np.uint8)
        occluded[:,int(.4*w):int(.6*w)]=background
        variants['middle20_occluded']=occluded
        hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        for name,hue in [('green_recolor',60),('yellow_recolor',30)]:
            changed=hsv.copy();changed[...,0][changed[...,1]>60]=hue
            variants[name]=cv2.cvtColor(changed,cv2.COLOR_HSV2BGR)
        for kind,variant in variants.items():
            record(variant,kind,row['sample_index'],row['split'],row['path'],row['label'])
        if len(records)%300==0:print(f'ROI probe records {len(records)}',flush=True)
    # Existing, fixed background probe coordinates; only development images.
    background_manifest=ROOT/'tmp/blue-plate-normal-g1/background-probe/report.json'
    backgrounds=json.loads(background_manifest.read_text(encoding='utf8'))['records']
    scenes=[]
    for row in backgrounds:
        original=b.read_image(ROOT/row['source']);x0,y0,x1,y1=row['crop']
        scenes.append((row['index'],row['source'],'development_background',original[y0:y1,x0:x1]))
    old_manifest=ROOT/'tmp/blue-plate-g1/final-letterbox720/samples.json'
    for index,row in enumerate(json.loads(old_manifest.read_text(encoding='utf8'))):
        if not row['label']:
            scenes.append((index,row['path'],'unlabeled_np',b.read_image(ROOT/row['path'])))
    scene_records=[]
    for index,path,kind,original in scenes:
        image=canvas720(original)
        tensor,ratio,left,top=detect['detect_pre_precessing'](image,(320,320))
        det.setInput(tensor);proposals=detect['post_precessing'](det.forward(),ratio,left,top)
        start=len(records)
        for p in proposals:
            if int(p[13])!=0:continue
            points=p[5:13].reshape(4,2).astype(int)
            record(warp(image,points),kind,index,'diagnostic_only',path)
        outputs=records[start:]
        accepted=any(x['accepted_color'] for x in outputs)
        if accepted:cv2.imwrite(str(out/f'scene-{kind}-{index:04}.jpg'),image)
        scene_records.append(dict(kind=kind,source=path,sample_index=index,detected=len(proposals),
                                  scored=len(outputs),accepted_color=accepted,outputs=outputs))
    summary={}
    for kind in sorted({r['kind'] for r in records}):
        group=[r for r in records if r['kind']==kind]
        summary[kind]=dict(total=len(group),**{key:sum(r[key] for r in group) for key in
            ['accepted_grammar','accepted_color','accepted_color_p90','accepted_hs25']},
            colors=dict(Counter(r['color_class'] for r in group)))
        if kind=='positive':
            summary[kind]['color_correct']=sum(r['accepted_color'] and r['code']==r['label'] for r in group)
            summary[kind]['color_wrong']=sum(r['accepted_color'] and r['code']!=r['label'] for r in group)
    files=[Path(__file__),comparison,background_manifest,old_manifest,rec_file,cls_file,det_file]
    report=dict(scope='Synthetic partial/recolored ROIs and correlated real scene crops; not independent negative acceptance.',
                heldout_images_read=0,roi_summary=summary,scene_summary={kind:dict(total=sum(r['kind']==kind for r in scene_records),
                    accepted_color=sum(r['kind']==kind and r['accepted_color'] for r in scene_records))
                    for kind in ['development_background','unlabeled_np']},
                source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    (out/'records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'scene-records.json').write_text(json.dumps(scene_records,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
