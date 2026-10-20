"""Strict eight-plate fitting gate and one bounded development trial.

Preserves Candidate and all previous experiment artifacts. No val/heldout reads.
"""
import copy
from collections import Counter
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
import experiment as e

OUT=e.ROOT/'tmp/blue-plate-char-segment/fit-gate'
FIXED_IDS=[0,2,3,4,9,13,28,31]


class FixedScaleStudent(e.Candidate):
    """Same convolution/BN parameters, no input-dependent energy division.

Existing BN learns train statistics and uses fixed running statistics at eval;
no new BN, channels or parameters. Dropout is disabled by the condition builder.
"""
    def forward(self,x):
        branches=[]
        for i,layer in enumerate(self.backbone):
            x=layer(x)
            if i==2:branches.append(F.avg_pool2d(x,(11,22),(11,4)))
            elif i==6:branches.append(F.avg_pool2d(x,(5,20),(5,4)))
            elif i==13:branches.append(F.avg_pool2d(x,(4,9),(2,2)))
            elif i==22:branches.append(x)
        return self.container(torch.cat(branches,1)).mean(2)


def build(condition,initial,device):
    torch.manual_seed(701)
    net=(FixedScaleStudent(8,native=True) if condition=='fixed_scale' else e.Candidate(8,native=True)).to(device)
    net.load_state_dict(initial)
    if condition!='original':
        for layer in net.modules():
            if isinstance(layer,nn.Dropout):layer.p=0
    return net


def energy_monitor(net):
    values={}
    def hook(i):
        def record(module,args,out):
            with torch.no_grad():
                f=out.detach()
                if i==2:f=F.avg_pool2d(f,(11,22),(11,4))
                elif i==6:f=F.avg_pool2d(f,(5,20),(5,4))
                elif i==13:f=F.avg_pool2d(f,(4,9),(2,2))
                energy=f.square().mean((1,2,3))
                values[str(i)]=dict(min=float(energy.min()),max=float(energy.max()),mean=float(energy.mean()),epsilon_hits=int((energy<1e-6).sum()))
        return record
    handles=[net.backbone[i].register_forward_hook(hook(i)) for i in (2,6,13,22)]
    return values,handles


def raw_stats(predictions,records):
    return dict(total=len(records),exact=sum(p['code']==r['source_transcript'] for p,r in zip(predictions,records)),
        lengths=dict(Counter(len(p['code']) for p in predictions)),
        blank_fraction=float(np.mean([p['blank_fraction'] for p in predictions])))


def ctc_backend_check(device):
    torch.manual_seed(19)
    cpu=torch.randn(3,66,35,requires_grad=True)
    gpu=cpu.detach().to(device).requires_grad_()
    labels=['皖A11223','皖AA796N','皖FLL589']
    a=e.ctc_loss(cpu,labels);b=e.ctc_loss(gpu,labels);a.backward();b.backward()
    error=float((cpu.grad-gpu.grad.cpu()).abs().max());loss_error=abs(float(a.detach())-float(b.detach()))
    assert error<1e-5 and loss_error<1e-5
    assert all(35>=len(label)+sum(x==y for x,y in zip(label,label[1:])) for label in labels)
    return dict(loss_error=loss_error,gradient_max_error=error,repeated_labels=labels)


def run(condition,initial,records,images,device,deadline,stage='fit'):
    folder=OUT/(condition if stage=='fit' else 'development');folder.mkdir(exist_ok=False)
    net=build(condition,initial,device);energies,handles=energy_monitor(net)
    optimizer=torch.optim.Adam(net.parameters(),lr=.001);rng=np.random.default_rng(701)
    train=[r for r in records if r['training_transcript'] is not None]
    tune=[r for r in records if r['split']=='tune']
    if stage=='fit':assert len(train)==8 and not tune
    else:assert len(train)==207 and len({r['sample_index'] for r in tune})==76
    maximum,interval=(2000,50) if stage=='fit' else (3000,250)
    logs=[];evaluations=[];streak=0;best_key=None;best=None;stop='step_limit'
    started=time.perf_counter()
    config=dict(condition=condition,stage=stage,max_steps=maximum,eval_interval=interval,seed=701,batch=16,
        optimizer='Adam',lr=.001,dropout=.5 if condition=='original' else 0,clip=5,
        dynamic_energy=condition!='fixed_scale',train_ids=[r['roi_index'] for r in train],
        tune_ids=[r['roi_index'] for r in tune],initial_sha256=e.sha(OUT/'initial.pt'),
        gate='greedy exact 8/8 at three consecutive scheduled evaluations; no format completion',
        no_improvement_stop='development only: after step 1500, stop if max calibrated correct in last 4 evaluations does not exceed all earlier evaluations',
        source_hashes={str(p.relative_to(e.ROOT)):e.sha(p) for p in [Path(__file__),Path(e.__file__),Path(e.__file__).with_name('lprnet_cost.py'),OUT/'fixed-eight.json']})
    e.write_json(folder/'config.json',config)

    def evaluate(step):
        nonlocal streak,best_key,best
        pred,loss=e.predict(net,train,images,device)
        result=dict(step=step,eval_loss=loss,train_eval=raw_stats(pred,train),energy=dict(energies))
        # Assess train/eval gap without changing the real BN buffers or training RNG.
        with torch.random.fork_rng(devices=[device.index or 0] if device.type=='cuda' else []):
            diagnostic=copy.deepcopy(net).train()
            subset=train[:16];x=e.tensor_input(images[[r['roi_index'] for r in subset]],device)
            with torch.inference_mode():
                y=diagnostic(x);p=e.decode(y);l=float(e.ctc_loss(y,[r['source_transcript'] for r in subset]))
            result['train_mode_first_batch']=dict(loss=l,**raw_stats(p,subset))
        if stage=='fit':
            streak=streak+1 if result['train_eval']['exact']==8 else 0
            result['consecutive_exact_evals']=streak
            result['predictions']=[dict(roi_index=r['roi_index'],label=r['source_transcript'],**p) for r,p in zip(train,pred)]
            key=(result['train_eval']['exact'],-loss,-step)
        else:
            tp,tl=e.predict(net,tune,images,device);cal=e.calibrate(tp,tune)
            result['tune']=dict(loss=tl,raw=raw_stats(tp,tune),**cal)
            result['predictions']=[dict(roi_index=r['roi_index'],label=r['source_transcript'],**p) for r,p in zip(tune,tp)]
            key=(cal['metrics']['correct'],-cal['metrics']['wrong'],-tl,-step)
        evaluations.append(result);e.write_json(folder/f'eval-{step:04d}.json',result)
        if best_key is None or key>best_key:
            best_key=key;torch.save(net.state_dict(),folder/'best.pt')
            best=dict(step=step,checkpoint_sha256=e.sha(folder/'best.pt'),
                exact=result['train_eval']['exact'],**({'tune':result['tune']} if stage!='fit' else {}))
        print(e.json.dumps({k:v for k,v in result.items() if k not in ('predictions','energy','train_mode_first_batch')},ensure_ascii=False),flush=True)

    evaluate(0)
    for step in range(1,maximum+1):
        if time.perf_counter()>=deadline:stop='shared_15minute_limit';break
        batch=train*2 if stage=='fit' else [train[int(i)] for i in rng.integers(len(train),size=16)]
        x=e.tensor_input(images[[r['roi_index'] for r in batch]],device);net.train();optimizer.zero_grad(set_to_none=True)
        y=net(x);loss=e.ctc_loss(y,[r['training_transcript'] for r in batch]);assert torch.isfinite(loss)
        loss.backward();assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in net.parameters())
        norm=nn.utils.clip_grad_norm_(net.parameters(),5);optimizer.step()
        logs.append(dict(step=step,loss=float(loss.detach()),gradient_norm=float(norm),energies=dict(energies)))
        if step%interval==0:
            evaluate(step)
            if stage=='fit' and streak>=3:stop='three_consecutive_exact_evaluations';break
            if stage!='fit' and step>=1500:
                counts=[r['tune']['metrics']['correct'] for r in evaluations]
                if max(counts[-4:])<=max(counts[:-4]):stop='no_calibrated_gain_last_four_evaluations';break
    actual=logs[-1]['step'] if logs else 0
    if evaluations[-1]['step']!=actual:evaluate(actual)
    passed=stage=='fit' and streak>=3
    torch.save(net.state_dict(),folder/'last.pt')
    summary=dict(condition=condition,stage=stage,passed_fitting_gate=passed,stop_reason=stop,steps=actual,
        seconds=time.perf_counter()-started,best=best,logs=logs,evaluations=evaluations,
        validation_images_read=0,heldout_images_read=0)
    e.write_json(folder/'summary.json',summary)
    for h in handles:h.remove()
    if stage!='fit':e.write_json(folder/'frozen.json',dict(condition=condition,**best,selection='tune only; checkpoint and threshold frozen; validation not opened'))
    return summary


def main():
    OUT.mkdir(exist_ok=False)
    torch.set_num_threads(2);torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    rows,images=e.reviewed_inputs();by_id={r['roi_index']:r for r in rows};fixed=[by_id[i] for i in FIXED_IDS]
    assert all(r['split']=='train' and r['training_transcript'] and r['full_visible'] for r in fixed)
    e.write_json(OUT/'fixed-eight.json',dict(records=[dict(r,native_sha256=e.array_sha(images[r['roi_index']])) for r in fixed],
        inputs_sha256=e.sha(e.OUT/'dev-inputs.npz'),visual_review_sha256=e.sha(e.OUT/'visual-review.json'),selection='predeclared indices; includes adjacent 88,99,LL,11,AA'))
    e.write_json(OUT/'ctc-backend-check.json',ctc_backend_check(device))
    torch.manual_seed(701);initial={k:v.clone() for k,v in e.Candidate(8,native=True).state_dict().items()}
    torch.save(initial,OUT/'initial.pt')
    start=time.perf_counter();deadline=start+900;results=[]
    for condition in ['original','no_dropout']:
        results.append(run(condition,initial,fixed,images,device,deadline))
    if not any(r['passed_fitting_gate'] for r in results) and time.perf_counter()<deadline:
        results.append(run('fixed_scale',initial,fixed,images,device,deadline))
    passed=[r for r in results if r['passed_fitting_gate']]
    development=None
    if passed and time.perf_counter()<deadline:
        chosen=min(passed,key=lambda r:(r['steps'],['original','no_dropout','fixed_scale'].index(r['condition'])))
        development=run(chosen['condition'],initial,rows,images,device,deadline,stage='development')
    summary=dict(conditions=[{k:v for k,v in r.items() if k not in ('logs','evaluations')} for r in results],
        development={k:v for k,v in development.items() if k not in ('logs','evaluations')} if development else None,
        total_new_steps=sum(r['steps'] for r in results)+(development['steps'] if development else 0),
        total_training_seconds=time.perf_counter()-start,budget_seconds=900,validation_images_read=0,heldout_images_read=0)
    e.write_json(OUT/'summary.json',summary);print(e.json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
