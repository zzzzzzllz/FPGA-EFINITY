"""Read-only analysis of the frozen 500-step experiment; no optimizer steps."""
from collections import Counter
import numpy as np
import torch
from torch import nn
import experiment as e


def summarize(predictions,records,threshold):
    return dict(metrics=e.metrics(predictions,records,threshold),
        exact=sum(p['code']==r['source_transcript'] for p,r in zip(predictions,records)),
        roi_count=len(records),length_histogram=dict(Counter(len(p['code']) for p in predictions)),
        common_outputs=Counter(p['code'] for p in predictions).most_common(12),
        mean_blank_fraction=float(np.mean([p['blank_fraction'] for p in predictions])))


def main():
    torch.set_num_threads(2)
    frozen=e.read_json(e.OUT/'pilot/frozen.json');path=e.OUT/'pilot'/frozen['checkpoint']
    assert e.sha(path)==frozen['checkpoint_sha256']
    records,images=e.reviewed_inputs()
    train=[r for r in records if r['split']=='train' and r['training_transcript'] is not None]
    tune=[r for r in records if r['split']=='tune']
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    weights=torch.load(path,map_location=device,weights_only=True)
    results={}
    for name,subset in [('train',train),('tune',tune)]:
        net=e.Candidate(8,native=True).to(device);net.load_state_dict(weights)
        pred,loss=e.predict(net,subset,images,device)
        results[name]=dict(summarize(pred,subset,frozen['threshold']),reviewed_label_ctc_loss=loss)
        # Deliberate diagnostic: replace running BN stats with current-batch stats,
        # keep dropout off, and discard all updated in-memory running buffers.
        net=e.Candidate(8,native=True).to(device);net.load_state_dict(weights);net.eval()
        for layer in net.modules():
            if isinstance(layer,nn.BatchNorm2d):layer.train()
        diagnostic=[]
        with torch.inference_mode():
            for start in range(0,len(subset),16):
                batch=subset[start:start+16]
                diagnostic.extend(e.decode(net(e.tensor_input(images[[r['roi_index'] for r in batch]],device))))
        results[name+'_batch_bn_diagnostic']=summarize(diagnostic,subset,frozen['threshold'])
    summary=e.read_json(e.OUT/'pilot/summary.json')
    logs=summary['logs']
    results['training_numerics']=dict(steps=len(logs),clip_fraction=summary['clip_fraction'],
        first_train_loss=logs[0]['loss'],last_train_loss=logs[-1]['loss'],
        branch_min_energy=min(v['min'] for r in logs for v in r['energies'].values()),
        epsilon_hits=sum(v['epsilon_hits'] for r in logs for v in r['energies'].values()),
        all_recorded_gradients_finite=all(np.isfinite(r['gradient_norm']) for r in logs))
    initial=torch.load(e.OUT/'pilot/step-0000.pt',map_location='cpu',weights_only=True)
    parameter_names={name for name,_ in net.named_parameters()}
    results['max_parameter_change']=max(float((weights[k].cpu()-v).abs().max()) for k,v in initial.items() if k in parameter_names)
    probe=e.DETECTOR/'rejection-probe/left20_removed-0001-0002.png'
    image=e.baseline.read_image(probe).astype(np.uint16)
    gray=((77*image[:,:,2]+150*image[:,:,1]+29*image[:,:,0])>>8).astype(np.uint8)
    net=e.Candidate(8,native=True).to(device);net.load_state_dict(weights);net.eval()
    with torch.inference_mode():prediction=e.decode(net(e.tensor_input(np.array([e.resize_q8(gray)]),device)))[0]
    results['known_teacher_completion_probe']=dict(path=str(probe.relative_to(e.ROOT)),sha256=e.sha(probe),prediction=prediction,
        accepted=bool(prediction['grammar'] and prediction['score']>=frozen['threshold']),original_split='development, sample_index=1')
    results['source_hashes']={str(p.relative_to(e.ROOT)):e.sha(p) for p in [path,e.Path(__file__),e.Path(e.__file__)]}
    results['optimizer_steps']=0;results['validation_images_read']=0;results['heldout_images_read']=0
    e.write_json(e.OUT/'pilot/failure-analysis.json',results)
    print(e.json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
