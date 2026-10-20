"""Frozen-weight train-only BN diagnosis and tune operating-point accounting."""
import copy
from collections import Counter
import numpy as np
import torch
from torch import nn
import experiment as e
import fit_gate as f


def bn_diagnosis(weights,condition,rows,images,device,with_labels):
    result={}
    for mode in ('eval','batch_stats_no_updates'):
        net=f.build(condition,weights,device).eval()
        # track_running_stats=False passes None to functional BN and skips its
        # counter/running-mean/variance updates. Dropout remains disabled.
        if mode!='eval':
            for module in net.modules():
                if isinstance(module,nn.BatchNorm2d):module.train();module.track_running_stats=False
        before={k:v.detach().clone() for k,v in net.state_dict().items()}
        moments={};hooks=[];energies,energy_hooks=f.energy_monitor(net)
        def moment_hook(name):
            def record(module,args):
                x=args[0].detach();mean=x.mean((0,2,3));var=x.var((0,2,3),unbiased=True)
                shift=(mean-module.running_mean)/(module.running_var+module.eps).sqrt()
                ratio=(var+module.eps)/(module.running_var+module.eps)
                moments[name]=dict(running_count=int(module.num_batches_tracked),
                    mean_shift_abs_avg=float(shift.abs().mean()),mean_shift_abs_max=float(shift.abs().max()),
                    variance_ratio_min=float(ratio.min()),variance_ratio_max=float(ratio.max()),variance_ratio_median=float(ratio.median()),
                    batch_mean=mean.cpu().tolist(),batch_variance_unbiased=var.cpu().tolist(),
                    running_mean=module.running_mean.cpu().tolist(),running_variance=module.running_var.cpu().tolist())
            return record
        for name,module in net.named_modules():
            if isinstance(module,nn.BatchNorm2d):hooks.append(module.register_forward_pre_hook(moment_hook(name)))
        predictions=[];batches=[]
        with torch.inference_mode():
            for start in range(0,len(rows),16):
                group=rows[start:start+16]
                # Neither labels nor loss participate in this inference call.
                y=net(e.tensor_input(images[[r['roi_index'] for r in group]],device))
                predictions.extend(e.decode(y))
                batches.append(dict(roi_indices=[r['roi_index'] for r in group],moments=copy.deepcopy(moments),energies=copy.deepcopy(energies)))
        assert all(torch.equal(before[k],v) for k,v in net.state_dict().items())
        for h in hooks+energy_hooks:h.remove()
        stats=dict(total=len(rows),lengths=dict(Counter(len(p['code']) for p in predictions)),
                   blank_fraction=float(np.mean([p['blank_fraction'] for p in predictions])))
        if with_labels:stats['exact']=sum(p['code']==r['source_transcript'] for r,p in zip(rows,predictions))
        result[mode]=dict(stats=stats,buffers_and_parameters_unchanged=True,batches=batches,
            predictions=[dict(roi_index=r['roi_index'],**p) for r,p in zip(rows,predictions)])
    result['changed_predictions']=sum(a['code']!=b['code'] for a,b in zip(result['eval']['predictions'],result['batch_stats_no_updates']['predictions']))
    return result


def inference(net,rows,images,device,batch_bn):
    net.eval()
    if batch_bn:
        for layer in net.modules():
            if isinstance(layer,nn.BatchNorm2d):layer.train()
    predictions=[];losses=[]
    with torch.inference_mode():
        for start in range(0,len(rows),16):
            group=rows[start:start+16]
            y=net(e.tensor_input(images[[r['roi_index'] for r in group]],device))
            predictions.extend(e.decode(y))
            losses.extend(e.ctc_loss(y,[r['training_transcript'] for r in group],'none').div(7).cpu().tolist())
    return dict(f.raw_stats(predictions,rows),loss=sum(losses)/len(losses))


def main():
    torch.set_num_threads(2)
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    records,images=e.reviewed_inputs();fixed=e.read_json(f.OUT/'fixed-eight.json')['records']
    train=[r for r in records if r['training_transcript'] is not None]
    results={}
    for name,path,rows,condition in [('dropout0_small',f.OUT/'no_dropout/last.pt',fixed,'no_dropout'),
                                    ('development_best',f.OUT/'development/best.pt',train,'original')]:
        weights=torch.load(path,map_location=device,weights_only=True)
        results[name]={}
        for mode in ['eval','batch_bn']:
            net=f.build(condition,weights,device)
            results[name][mode]=inference(net,rows,images,device,mode=='batch_bn')
        results[name]['checkpoint_sha256']=e.sha(path)
    tune=[r for r in records if r['split']=='tune'];by_id={r['roi_index']:r for r in tune}
    zero_error=[]
    summary=e.read_json(f.OUT/'development/summary.json')
    for row in summary['evaluations']:
        ps=row['predictions'];rs=[by_id[p['roi_index']] for p in ps]
        options=[(t,e.metrics(ps,rs,t)) for t in [1.]+sorted({p['score'] for p in ps if p['grammar']},reverse=True)]
        t,m=max([x for x in options if x[1]['wrong']==0],key=lambda x:(x[1]['correct'],x[0]))
        zero_error.append(dict(step=row['step'],threshold=t,metrics=m))
    results['zero_error_tune_curve']=zero_error
    results['interpretation']='BN diagnosis uses training images only, dropout disabled, isolated models with updated running buffers discarded; not a deployable fix or tune training.'
    results['optimizer_steps']=0;results['validation_images_read']=0;results['heldout_images_read']=0
    e.write_json(f.OUT/'analysis.json',results)
    path=f.OUT/'development/best.pt';checkpoint_hash=e.sha(path)
    weights=torch.load(path,map_location=device,weights_only=True)
    bn=dict(train=bn_diagnosis(weights,'original',train,images,device,True),
            tune_unlabeled=bn_diagnosis(weights,'original',tune,images,device,False),
            checkpoint_sha256=checkpoint_hash,optimizer_steps=0,validation_images_read=0,heldout_images_read=0,
            explanation='Tune inputs only; no labels/loss, no backward, no BN buffers/counters or parameters updated, no model saved; trained checkpoint remains unchanged.')
    assert e.sha(path)==checkpoint_hash
    e.write_json(f.OUT/'bn-diagnosis.json',bn)
    print(e.json.dumps({k:{mode:data['stats'] for mode,data in v.items() if isinstance(data,dict) and 'stats' in data} for k,v in bn.items() if k in ('train','tune_unlabeled')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
