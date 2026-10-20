"""Bounded offline student experiment; never load heldout images.

Prepared inputs use frozen detector320 corners and the existing Q32 sampler.
Only individually reviewed full crops can carry a full training transcript.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import torch
from torch import nn
from torch.nn import functional as F

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/blue_plate'))
import baseline as baseline
from geometry_sampler import sample_integer
from compare_hyperlpr import inspected_functions, grammar, SOURCE
from lprnet_cost import Candidate

OUT=ROOT/'tmp/blue-plate-char-segment/experiment'
DETECTOR=ROOT/'tmp/blue-plate-normal-g1/mature-detector'
SAMPLES=ROOT/'tmp/blue-plate-normal-g1/full-dual-local-geometry/samples.json'
CLASSES=json.loads((ROOT/'tools/blue_plate/char_model/candidate/interface.json').read_text(encoding='utf8'))['classes']
BLANK=len(CLASSES)

def read_json(path):return json.loads(path.read_text(encoding='utf8'))
def write_json(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def array_sha(a):return hashlib.sha256(a.tobytes()).hexdigest()

def axis_lut(source,target):
    # Half-pixel coordinates, edge clamp, Q8 fractions rounded half up; integer-only.
    den=2*target
    coordinate=np.clip((2*np.arange(target,dtype=np.int64)+1)*source-target,0,(source-1)*den)
    lo,rem=np.divmod(coordinate,den)
    fraction=(rem*512+den)//(2*den)
    lo+=fraction//256;fraction%=256
    return lo,np.minimum(lo+1,source-1),fraction

def resize_q8(image,height=48,width=160):
    if image.dtype!=np.uint8 or image.ndim not in (2,3):raise ValueError('Expected uint8 gray or BGR')
    y0,y1,fy=axis_lut(image.shape[0],height);x0,x1,fx=axis_lut(image.shape[1],width)
    wx=fx[None,:];wy=fy[:,None]
    if image.ndim==3:wx=wx[...,None];wy=wy[...,None]
    im=image.astype(np.int64)
    acc=(im[y0[:,None],x0]*(256-wx)*(256-wy)+im[y0[:,None],x1]*wx*(256-wy)
         +im[y1[:,None],x0]*(256-wx)*wy+im[y1[:,None],x1]*wx*wy)
    return ((acc+32768)>>16).astype(np.uint8)

def resize_checks():
    # Independent scalar rational coordinates cover up/down-sampling and clamping.
    from fractions import Fraction
    rng=np.random.default_rng(701)
    checks=[]
    for h,w,oh,ow in [(64,224,48,160),(64,224,24,94),(2,3,7,9),(1,1,5,7),(7,9,7,9)]:
        image=rng.integers(0,256,(h,w),dtype=np.uint8);gold=np.zeros((oh,ow),np.uint8)
        def point(i,src,dst):
            u=min(max(Fraction((2*i+1)*src-dst,2*dst),0),src-1)
            lo=int(u);f=int((u-lo)*256+Fraction(1,2));lo+=f//256
            return lo,min(lo+1,src-1),f%256
        for y in range(oh):
            y0,y1,fy=point(y,h,oh)
            for x in range(ow):
                x0,x1,fx=point(x,w,ow)
                acc=int(image[y0,x0])*(256-fx)*(256-fy)+int(image[y0,x1])*fx*(256-fy)
                acc+=int(image[y1,x0])*(256-fx)*fy+int(image[y1,x1])*fx*fy
                gold[y,x]=(acc+32768)>>16
        assert np.array_equal(resize_q8(image,oh,ow),gold)
        for value in (0,127,255):assert np.all(resize_q8(np.full((h,w),value,np.uint8),oh,ow)==value)
        checks.append(dict(source=[h,w],target=[oh,ow],scalar_match=True))
    return checks

def source_frame(row,sample):
    if row['split']=='heldout':raise ValueError('Heldout image access forbidden')
    path=ROOT/row['path']
    if sha(path)!=sample['sha256']:raise ValueError('Source hash changed')
    source=baseline.read_image(path);h,w=source.shape[:2]
    scale=min(1280/w,720/h);nw,nh=round(w*scale),round(h*scale)
    dx,dy=(1280-nw)//2,(720-nh)//2
    image=np.zeros((720,1280,3),np.uint8)
    image[dy:dy+nh,dx:dx+nw]=cv2.resize(source,(nw,nh),interpolation=cv2.INTER_AREA)
    return image

def prepare(split):
    OUT.mkdir(parents=True,exist_ok=True)
    if split=='validation' and not (OUT/'pilot/frozen.json').is_file():
        raise ValueError('Freeze checkpoint before opening validation images')
    samples=read_json(SAMPLES);rows=read_json(DETECTOR/'comparison-records.json')
    dev=[s for s in samples if s['split']=='development']
    assert len(dev)==304 and len({s['label'] for s in dev})==304
    ordered=sorted({s['label'] for s in dev},key=lambda x:hashlib.sha256(('701:'+x).encode()).hexdigest())
    tune=set(ordered[:76]);records=[];rgb=[];gray=[]
    for row in rows:
        if row['split']!=split:continue
        sample=samples[row['sample_index']]
        assert sample['path']==row['path'] and sample['label']==row['label'] and sample['split']==split
        image=source_frame(row,sample)
        for ci,candidate in enumerate(row['detector320']):
            if candidate.get('reason')=='double_line':continue
            plate,matrix=sample_integer(image,candidate['points'],32,integer_solver=True)
            p=plate.astype(np.uint16);g=((77*p[:,:,2]+150*p[:,:,1]+29*p[:,:,0])>>8).astype(np.uint8)
            record=dict(roi_index=len(rgb),sample_index=row['sample_index'],candidate_index=ci,path=row['path'],
                source_sha256=sample['sha256'],roi_gray_sha256=array_sha(g),roi_bgr_sha256=array_sha(plate),
                identity=row['label'],source_transcript=row['label'],group=row['label'],
                split='tune' if split=='development' and row['label'] in tune else 'train' if split=='development' else split,
                original_split=split,points=candidate['points'],inverse_q32=matrix.tolist(),
                teacher_cached=candidate,full_visible=None,training_transcript=None)
            records.append(record);rgb.append(plate);gray.append(g)
    prefix='dev' if split=='development' else 'val'
    np.savez_compressed(OUT/f'{prefix}-inputs.npz',bgr=np.array(rgb),gray=np.array(gray),
                        native=np.array([resize_q8(g) for g in gray]),small=np.array([resize_q8(g,24,94) for g in gray]))
    write_json(OUT/f'{prefix}-manifest.json',dict(records=records,resize_checks=resize_checks(),
        heldout_image_bytes_read=0,grouping='seed701 identity hash; 228 train / 76 tune; exact hash disjoint; session unknown, near-duplicate disjointness not proven',
        source_hashes={str(p.relative_to(ROOT)):sha(p) for p in [SAMPLES,DETECTOR/'comparison-records.json',Path(__file__),ROOT/'tools/blue_plate/geometry_sampler.py']},
        inputs_sha256=sha(OUT/f'{prefix}-inputs.npz')))
    if split=='development':
        contact_sheets(records,np.array(rgb))
        write_json(OUT/'grouping.json',dict(train=[x for x in ordered if x not in tune],tune=[x for x in ordered if x in tune],
                   all_source_groups=304,session_disjoint=False,heldout_image_bytes_read=0))
    print(f'Prepared {len(records)} {split} ROIs',flush=True)

def contact_sheets(records,plates):
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',17)
    folder=OUT/'review';folder.mkdir(exist_ok=True)
    for start in range(0,len(records),32):
        sheet=Image.new('RGB',(1000,8*104),'#eeeeee');draw=ImageDraw.Draw(sheet)
        for i,r in enumerate(records[start:start+32]):
            x=(i%4)*250;y=(i//4)*104
            draw.text((x+4,y+2),f"{r['roi_index']:03d} {r['source_transcript']} {r['split']}",font=font,fill='black')
            sheet.paste(Image.fromarray(plates[r['roi_index']][:,:,::-1]),(x+4,y+30))
        sheet.save(folder/f'{start:03d}-{min(start+31,len(records)-1):03d}.png')

def diagnose():
    cv2.setNumThreads(2)
    manifest=read_json(OUT/'dev-manifest.json');data=np.load(OUT/'dev-inputs.npz')
    assert sha(OUT/'dev-inputs.npz')==manifest['inputs_sha256']
    model=DETECTOR/'rpv3_mdict_160_r3.onnx'
    assert sha(model)=='8fb08b5db2adeccf43b05006bbbf409e4659d08d72e46a62631c00ff751eaeb3'
    net=cv2.dnn.readNetFromONNX(str(model))
    token=ast.literal_eval(next(n.value for n in ast.parse((SOURCE/'common/tokenize.py').read_text(encoding='utf8')).body if isinstance(n,ast.Assign)))
    encode=inspected_functions(SOURCE/'inference/recognition.py',['encode_images'])['encode_images']
    rows=[]
    for r in manifest['records']:
        i=r['roi_index'];row={k:r[k] for k in ['roi_index','sample_index','split','source_transcript']}
        # Same integer resize for all three: isolates gray conversion and loss from 24x94.
        variants=dict(rgb_native=resize_q8(data['bgr'][i]),gray_native=np.repeat(data['native'][i,:,:,None],3,2),
                      gray_small_restored=np.repeat(resize_q8(data['small'][i])[:,:,None],3,2))
        for mode,image in variants.items():
            net.setInput(encode(image,image.shape[1]/image.shape[0],(48,160))[None])
            p=net.forward();assert p.shape==(1,20,78)
            p=p[0];indices=p.argmax(1);keep=[t for t,k in enumerate(indices) if k and (t==0 or k!=indices[t-1])]
            unknown=any(indices[t]>=len(token) for t in keep)
            code='' if unknown else ''.join(token[indices[t]] for t in keep)
            row[mode]=dict(code=code,grammar=grammar(code),confidence=float(np.mean([p[t,indices[t]] for t in keep])) if keep and not unknown else 0,
                          unknown_class=bool(unknown))
        rows.append(row)
        if len(rows)%50==0:print(f'Teacher input comparison {len(rows)}/{len(manifest["records"])}',flush=True)
    metrics={mode:aggregate(rows,mode) for mode in variants}
    write_json(OUT/'input-diagnosis.json',dict(records=rows,metrics=metrics,teacher_output=[1,20,78],
        teacher_model_sha256=sha(model),inputs_sha256=sha(OUT/'dev-inputs.npz'),heldout_image_bytes_read=0,
        interpretation='307 automatic ROIs / 304 developmental source images; diagnostic teacher overlap unknown; no training labels inferred'))
    print(json.dumps(metrics,ensure_ascii=False),flush=True)

def aggregate(rows,mode):
    by_sample={}
    for r in rows:by_sample.setdefault(r['sample_index'],[]).append(r)
    counts=Counter(total=len(by_sample),correct=0,wrong=0,reject=0)
    for group in by_sample.values():
        valid=[r[mode] for r in group if r[mode]['grammar']]
        selected=max(valid,key=lambda r:r['confidence']) if valid else None
        counts['reject' if selected is None else 'correct' if selected['code']==group[0]['source_transcript'] else 'wrong']+=1
    return dict(counts)

def reviewed_inputs():
    manifest=read_json(OUT/'dev-manifest.json');review=read_json(OUT/'visual-review.json')
    assert review['manifest_sha256']==sha(OUT/'dev-manifest.json')
    assert sha(OUT/'dev-inputs.npz')==manifest['inputs_sha256']
    decisions={r['roi_index']:r for r in review['records']}
    assert set(decisions)==set(range(len(manifest['records'])))
    records=[]
    for r in manifest['records']:
        d=decisions[r['roi_index']]
        assert d['roi_gray_sha256']==r['roi_gray_sha256']
        records.append(dict(r,**{k:d[k] for k in ['full_visible','training_transcript','review_reason']}))
    return records,np.load(OUT/'dev-inputs.npz')['native']

def tensor_input(images,device):return torch.as_tensor((images.astype(np.float32)-127.5)/128,device=device)[:,None]

def ctc_loss(logits,labels,reduction='mean'):
    target=torch.tensor([[CLASSES.index(c) for c in label] for label in labels],dtype=torch.long,device=logits.device)
    if target.shape[1]!=7:raise ValueError('Seven-character full labels required')
    return F.ctc_loss(logits.log_softmax(1).permute(2,0,1),target,
                      torch.full((len(labels),),logits.shape[2],dtype=torch.long),
                      torch.full((len(labels),),7,dtype=torch.long),blank=BLANK,reduction=reduction,zero_infinity=False)

def decode(logits):
    logp=logits.log_softmax(1).permute(0,2,1).cpu()
    rows=[]
    for p in logp:
        path=p.argmax(1).tolist();ids=[v for i,v in enumerate(path) if v!=BLANK and (i==0 or v!=path[i-1])]
        code=''.join(CLASSES[c] for c in ids);valid=grammar(code);score=None
        if valid:
            # Native CTC forward computes the total probability of this fixed label.
            loss=F.ctc_loss(p[:,None],torch.tensor(ids),torch.tensor([len(p)]),torch.tensor([len(ids)]),blank=BLANK,reduction='sum')
            if not torch.isfinite(loss):raise ValueError('Non-finite decoded-label probability')
            score=-float(loss)/7
        rows.append(dict(code=code,grammar=valid,score=score,blank_fraction=path.count(BLANK)/len(path)))
    return rows

def metrics(predictions,records,threshold):
    groups={}
    for r,p in zip(records,predictions):groups.setdefault(r['sample_index'],[]).append((r,p))
    counts=Counter(total=len(groups),correct=0,wrong=0,reject=0,raw_exact=0)
    for group in groups.values():
        counts['raw_exact']+=any(p['code']==r['source_transcript'] for r,p in group)
        valid=[(r,p) for r,p in group if p['grammar'] and p['score']>=threshold]
        selected=max(valid,key=lambda rp:rp[1]['score']) if valid else None
        counts['reject' if selected is None else 'correct' if selected[1]['code']==selected[0]['source_transcript'] else 'wrong']+=1
    return dict(counts)

def calibrate(predictions,records):
    # Stable finite reject-all threshold; all valid CTC log probabilities are <=0.
    thresholds=[1.0]+sorted({p['score'] for p in predictions if p['grammar']},reverse=True)
    options=[(threshold,metrics(predictions,records,threshold)) for threshold in thresholds]
    allowed=[x for x in options if x[1]['wrong']<=3]
    threshold,result=max(allowed,key=lambda x:(x[1]['correct'],-x[1]['wrong'],x[0]))
    return dict(threshold=threshold,metrics=result,unfiltered=metrics(predictions,records,-1e30))

def predict(net,records,images,device):
    net.eval();predictions=[];losses=[]
    with torch.inference_mode():
        for start in range(0,len(records),16):
            group=records[start:start+16];x=tensor_input(images[[r['roi_index'] for r in group]],device)
            y=net(x);predictions.extend(decode(y))
            complete=[i for i,r in enumerate(group) if r.get('full_visible')]
            if complete:losses.extend(ctc_loss(y[complete],[group[i]['source_transcript'] for i in complete],reduction='none').div(7).cpu().tolist())
    return predictions,float(np.mean(losses)) if losses else None

def baseline_comparison(records):
    paths={r['path'] for r in records}
    old=read_json(ROOT/'tmp/blue-plate-normal-g1/integer-geometry-solver/q32-results.json')
    rows=[r for r in old if r['path'] in paths]
    assert len(rows)==len(paths)
    return dict(source='frozen old pipeline on same source groups; no teacher accuracy requirement',
                metrics=baseline.summarize(rows,0,0))

def train(mode):
    records,images=reviewed_inputs();train_rows=[r for r in records if r['split']=='train' and r['training_transcript'] is not None]
    tune_rows=[r for r in records if r['split']=='tune']
    if not train_rows:raise ValueError('No reviewed complete training data')
    # Fixed total budget: 100 fitting-check steps + 400 independent pilot steps.
    maximum=100 if mode=='sanity' else 400
    folder=OUT/mode;folder.mkdir(exist_ok=False)
    if mode=='pilot':
        sanity=read_json(OUT/'sanity/summary.json')
        if not sanity['numerically_valid'] or sanity['final_loss']>=sanity['initial_loss']:
            raise ValueError('Fitting check failed; inspect it before pilot')
    torch.manual_seed(701);np.random.seed(701);torch.set_num_threads(2)
    torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    net=Candidate(8,native=True).to(device);opt=torch.optim.Adam(net.parameters(),lr=.001)
    energies={}
    def energy_hook(index):
        def hook(module,args,output):
            if not module.training:return
            with torch.no_grad():
                f=output.detach()
                if index==2:f=F.avg_pool2d(f,(11,22),(11,4))
                elif index==6:f=F.avg_pool2d(f,(5,20),(5,4))
                elif index==13:f=F.avg_pool2d(f,(4,9),(2,2))
                e=f.square().mean((1,2,3))
                energies[str(index)]=dict(min=float(e.min()),max=float(e.max()),epsilon_hits=int((e<1e-6).sum()))
        return hook
    for index in (2,6,13,22):net.backbone[index].register_forward_hook(energy_hook(index))
    if mode=='sanity':train_rows=train_rows[:1];eval_rows=train_rows
    else:eval_rows=tune_rows
    samples={}
    for r in train_rows:samples.setdefault(r['sample_index'],[]).append(r)
    groups=list(samples.values());rng=np.random.default_rng(701)
    source_hashes={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),Path(__file__).with_name('lprnet_cost.py'),OUT/'dev-manifest.json',OUT/'visual-review.json',OUT/'dev-inputs.npz']}
    write_json(folder/'config.json',dict(mode=mode,seed=701,max_steps=maximum,max_total_steps=500,max_total_seconds=1800,
        batch_size=16,optimizer='Adam',lr=.001,clip_norm=5,train_groups=len(groups),eval_groups=len({r['sample_index'] for r in eval_rows}),
        device=str(device),torch=torch.__version__,source_hashes=source_hashes,heldout_image_bytes_read=0,
        baseline=baseline_comparison(eval_rows),reviewer='Codex visual inspection, not a human annotator signature'))
    snapshots=[];logs=[];start=time.perf_counter();prior_seconds=0 if mode=='sanity' else sanity['seconds']
    initial_pred,initial_loss=predict(net,eval_rows,images,device)
    best_key=None;best=None
    def snapshot(step):
        nonlocal best_key,best
        pred,loss=predict(net,eval_rows,images,device);cal=calibrate(pred,eval_rows)
        result=dict(step=step,loss=loss,**cal,mean_blank_fraction=float(np.mean([p['blank_fraction'] for p in pred])))
        key=(cal['metrics']['correct'],-cal['metrics']['wrong'],-loss if loss is not None else -1e30,-step)
        path=folder/f'step-{step:04d}.pt';torch.save(net.state_dict(),path)
        write_json(folder/f'step-{step:04d}.json',dict(**result,records=[dict(roi_index=r['roi_index'],sample_index=r['sample_index'],label=r['source_transcript'],**p) for r,p in zip(eval_rows,pred)]))
        snapshots.append(result)
        if best_key is None or key>best_key:best_key=key;best=dict(result,checkpoint=path.name,checkpoint_sha256=sha(path))
        print(json.dumps(result,ensure_ascii=False),flush=True)
    snapshot(0)
    for step in range(1,maximum+1):
        if time.perf_counter()-start+prior_seconds>=1800:break
        net.train()
        batch=[group[int(rng.integers(len(group)))] for group in [groups[int(i)] for i in rng.integers(len(groups),size=16)]]
        x=tensor_input(images[[r['roi_index'] for r in batch]],device)
        opt.zero_grad(set_to_none=True);y=net(x);loss=ctc_loss(y,[r['training_transcript'] for r in batch])
        if not torch.isfinite(loss):raise ValueError(f'Non-finite loss at step {step}')
        loss.backward()
        if not all(p.grad is not None and torch.isfinite(p.grad).all() for p in net.parameters()):raise ValueError('Non-finite gradient')
        norm=nn.utils.clip_grad_norm_(net.parameters(),5);opt.step()
        logs.append(dict(step=step,loss=float(loss.detach()),gradient_norm=float(norm),clipped=bool(norm>5),energies=dict(energies)))
        if step in (100,250,maximum):snapshot(step)
    actual_step=logs[-1]['step'] if logs else 0
    if snapshots[-1]['step']!=actual_step:snapshot(actual_step)
    final_pred,final_loss=predict(net,eval_rows,images,device)
    summary=dict(numerically_valid=True,optimizer_steps=actual_step,initial_loss=initial_loss,final_loss=final_loss,
        seconds=time.perf_counter()-start,clip_fraction=sum(r['clipped'] for r in logs)/len(logs) if logs else 0,
        best=best,snapshots=snapshots,logs=logs,heldout_image_bytes_read=0)
    write_json(folder/'summary.json',summary)
    if mode=='pilot':
        # Checkpoint/threshold is frozen using tune data before any validation bytes.
        write_json(folder/'frozen.json',dict(**best,source_hashes=source_hashes,selection='max tune correct under <=3 wrong; then fewer wrong, lower reviewed tune loss, earlier step',
                   total_optimizer_steps=sanity['optimizer_steps']+actual_step,total_seconds=prior_seconds+summary['seconds']))
    print(f'{mode} finished: {actual_step} steps, {summary["seconds"]:.1f}s',flush=True)

def rejection_probe():
    frozen=read_json(OUT/'pilot/frozen.json');checkpoint=OUT/'pilot'/frozen['checkpoint']
    assert sha(checkpoint)==frozen['checkpoint_sha256']
    records,images=reviewed_inputs();raw=np.load(OUT/'dev-inputs.npz')['gray']
    chosen=[r for r in records if r['split']=='tune' and r['full_visible']][:16]
    net=Candidate(8,native=True).eval();net.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True))
    probes=[];modes={}
    for r in chosen:
        g=raw[r['roi_index']]
        for mode,pixels in [('left20_removed',g[:,45:]),('right20_removed',g[:,:179]),
                            ('top25_removed',g[16:]),('bottom25_removed',g[:48]),('blank',np.zeros_like(g))]:
            probes.append(dict(parent_roi_index=r['roi_index'],mode=mode,pixels=resize_q8(pixels)))
    with torch.inference_mode():
        predictions=decode(net(tensor_input(np.array([r['pixels'] for r in probes]),torch.device('cpu'))))
    for r,p in zip(probes,predictions):
        del r['pixels'];r.update(p,accepted=bool(p['grammar'] and p['score']>=frozen['threshold']))
        counts=modes.setdefault(r['mode'],dict(total=0,accepted=0));counts['total']+=1;counts['accepted']+=r['accepted']
    write_json(OUT/'pilot/rejection-probe.json',dict(records=probes,metrics=modes,threshold=frozen['threshold'],
        interpretation='Synthetic crop-removal stress probes, no full-text training labels; rejection alone does not establish useful recognition',
        heldout_image_bytes_read=0))
    print(json.dumps(modes),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare-dev','prepare-val','diagnose','sanity','pilot','rejection-probe'])
    args=p.parse_args()
    if args.mode.startswith('prepare'):prepare('development' if args.mode.endswith('dev') else 'validation')
    elif args.mode=='diagnose':diagnose()
    elif args.mode in ('sanity','pilot'):train(args.mode)
    elif args.mode=='rejection-probe':rejection_probe()

if __name__=='__main__':main()
