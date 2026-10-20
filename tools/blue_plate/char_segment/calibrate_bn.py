"""One official update_bn pass, train-only, zero optimizer steps."""
import inspect
from pathlib import Path
import torch
from torch import nn
from torch.optim.swa_utils import update_bn
import experiment as e
import fit_gate as f


def main():
    out=e.ROOT/'tmp/blue-plate-char-segment/bn-calibration';out.mkdir(exist_ok=False)
    torch.set_num_threads(2)
    source=f.OUT/'development/best.pt';frozen=e.read_json(f.OUT/'development/frozen.json')
    assert e.sha(source)==frozen['checkpoint_sha256']
    records,images=e.reviewed_inputs()
    train=[r for r in records if r['training_transcript'] is not None]
    tune=[r for r in records if r['split']=='tune']
    assert len(train)==207 and all(r['split']=='train' for r in train)
    assert len({r['sample_index'] for r in tune})==76
    assert not {r['group'] for r in train}&{r['group'] for r in tune}
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    weights=torch.load(source,map_location=device,weights_only=True)
    net=f.build('original',weights,device).eval()
    before={k:v.detach().clone() for k,v in net.state_dict().items()}
    parameters=set(dict(net.named_parameters()))
    dropout={name:module.p for name,module in net.named_modules() if isinstance(module,nn.Dropout)}
    assert len(dropout)==2
    loader=[e.tensor_input(images[[r['roi_index'] for r in train[start:start+16]]],torch.device('cpu')) for start in range(0,len(train),16)]
    implementation=Path(inspect.getfile(inspect.unwrap(update_bn)))
    config=dict(source_checkpoint=str(source.relative_to(e.ROOT)),source_checkpoint_sha256=e.sha(source),
        source_hashes={str(p):e.sha(p) for p in [Path(__file__),implementation,e.OUT/'dev-manifest.json',e.OUT/'visual-review.json',e.OUT/'dev-inputs.npz']},
        train_indices=[r['roi_index'] for r in train],native_sha256=[e.array_sha(images[r['roi_index']]) for r in train],
        batch_sizes=[len(x) for x in loader],order='original reviewed manifest order',passes=1,optimizer_steps=0,
        algorithm='official torch.optim.swa_utils.update_bn, dropout p temporarily 0; default cumulative batch averaging',
        original_dropout=dropout,original_threshold=frozen['tune']['threshold'],validation_images_read=0,heldout_images_read=0)
    e.write_json(out/'config.json',config)
    for name,module in net.named_modules():
        if name in dropout:module.p=0
    update_bn(loader,net,device=device)
    for name,module in net.named_modules():
        if name in dropout:module.p=dropout[name]
    net.eval()
    after=net.state_dict();changes=[k for k in before if not torch.equal(before[k],after[k])]
    assert not parameters&set(changes)
    assert all(k.endswith(('running_mean','running_var','num_batches_tracked')) for k in changes)
    assert all(p.grad is None for p in net.parameters())
    counters={k:int(v) for k,v in after.items() if k.endswith('num_batches_tracked')}
    assert all(v==len(loader) for v in counters.values())
    checkpoint=out/'calibrated.pt';torch.save(after,checkpoint)
    # The independent artifact is frozen before any tune inference.
    e.write_json(out/'frozen.json',dict(checkpoint_sha256=e.sha(checkpoint),source_checkpoint_sha256=e.sha(source),
        all_parameters_equal=True,changed_buffers=changes,counters=counters,dropout_restored=True,optimizer_steps=0))
    immutable={k:v.detach().clone() for k,v in after.items()}
    report={}
    for name,model in [('original',f.build('original',weights,device)),('calibrated',net)]:
        tr,tl=e.predict(model,train,images,device);pr,pl=e.predict(model,tune,images,device)
        report[name]=dict(train=dict(loss=tl,**f.raw_stats(tr,train)),
            tune_loss=pl,original_threshold=frozen['tune']['threshold'],
            at_original_threshold=e.metrics(pr,tune,frozen['tune']['threshold']),
            calibrated_le3=e.calibrate(pr,tune),
            predictions=[dict(roi_index=r['roi_index'],sample_index=r['sample_index'],label=r['source_transcript'],**p) for r,p in zip(tune,pr)])
    assert all(torch.equal(immutable[k],v) for k,v in net.state_dict().items())
    assert e.sha(source)==frozen['checkpoint_sha256']
    report.update(optimizer_steps=0,eval_state_unchanged=True,source_checkpoint_unchanged=True,
                  calibrated_checkpoint_sha256=e.sha(checkpoint),baseline_same_tune=dict(correct=49,wrong=0,reject=27),
                  validation_images_read=0,heldout_images_read=0)
    e.write_json(out/'results.json',report)
    print(e.json.dumps({k:{a:b for a,b in v.items() if a!='predictions'} if isinstance(v,dict) else v for k,v in report.items()},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
