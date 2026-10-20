"""Shape/cost contract only. No optimizer or replacement weights.

The small block/backbone are adapted from sirius-ai/LPRNet_Pytorch (Apache-2.0),
commit 7c976664b3f3879efabeaff59c7a117e49d5f29e. See lprnet-reference-LICENSE.txt.
This file changes channels, spatial strides, heads, context pooling and scaling.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import torch
from torch import nn
from torch.nn import functional as F

ROOT=Path(__file__).resolve().parents[3]
RESEARCH=ROOT/'tmp/blue-plate-review/mature-research'
OUT=ROOT/'tmp/blue-plate-char-segment/lprnet-research'
SOURCE=RESEARCH/'lprnet/model/LPRNet.py'

class Block(nn.Module):
    def __init__(self,ci,co):
        super().__init__();b=co//4
        self.ops=nn.Sequential(nn.Conv2d(ci,b,1),nn.ReLU(),nn.Conv2d(b,b,(3,1),padding=(1,0)),nn.ReLU(),
            nn.Conv2d(b,b,(1,3),padding=(0,1)),nn.ReLU(),nn.Conv2d(b,co,1))
    def forward(self,x):return self.ops(x)

class ChannelSpatialPool(nn.Module):
    def __init__(self,channel_stride,spatial_stride):
        super().__init__();self.cs=channel_stride;self.ss=spatial_stride
    def forward(self,x):return F.max_pool2d(x[:,::self.cs],3,self.ss)

class Candidate(nn.Module):
    """Local height-reduced variant, not an exact reconstruction of paper reduced."""
    def __init__(self,stem=8,inputs=1,classes=66,native=False):
        super().__init__();c=stem;self.native=native;stride_h=2 if native else 1
        self.backbone=nn.Sequential(nn.Conv2d(inputs,c,3),nn.BatchNorm2d(c),nn.ReLU(),
            ChannelSpatialPool(1,(2,1)),Block(c,2*c),nn.BatchNorm2d(2*c),nn.ReLU(),
            ChannelSpatialPool(2,(stride_h,2)),Block(c,4*c),nn.BatchNorm2d(4*c),nn.ReLU(),
            Block(4*c,4*c),nn.BatchNorm2d(4*c),nn.ReLU(),ChannelSpatialPool(4,(stride_h,2)),nn.Dropout(0.5),
            nn.Conv2d(c,4*c,(1,4)),nn.BatchNorm2d(4*c),nn.ReLU(),nn.Dropout(0.5),
            nn.Conv2d(4*c,classes,(1 if native else 3,1)),nn.BatchNorm2d(classes),nn.ReLU())
        self.container=nn.Conv2d(7*c+classes,classes,1)
    def forward(self,x):
        branches=[]
        for i,m in enumerate(self.backbone):
            x=m(x)
            if i==2:branches.append(F.avg_pool2d(x,(11,22),(11,4)) if self.native else F.avg_pool2d(x,5,5))
            if i==6:branches.append(F.avg_pool2d(x,(5,20),(5,4)) if self.native else F.avg_pool2d(x,(3,5),(2,5)))
            if i==13:branches.append(F.avg_pool2d(x,(4,9),(2,2)) if self.native else F.avg_pool2d(x,(2,10),(2,2)))
            if i==22:branches.append(x)
        branches=[f/f.square().mean((1,2,3),keepdim=True).clamp_min(1e-6) for f in branches]
        return self.container(torch.cat(branches,1)).mean(2)

def profile(net,inputs):
    records=[];hooks=[];kept=[]
    def hook(name):
        def fn(m,args,out):
            if not isinstance(out,torch.Tensor):return
            r=dict(name=name,type=type(m).__name__,input=list(args[0].shape),output=list(out.shape),output_elements=out.numel())
            if isinstance(m,nn.Conv2d):
                k=m.in_channels*m.kernel_size[0]*m.kernel_size[1]
                r.update(weights=m.weight.numel(),biases=m.out_channels,k=k,macs=out.numel()*k,
                         dots=out.shape[2]*out.shape[3],channels=m.out_channels)
            records.append(r)
        return fn
    for name,m in net.named_modules():
        if isinstance(m,(nn.Conv2d,nn.MaxPool3d,ChannelSpatialPool)):hooks.append(m.register_forward_hook(hook(name)))
    for i in [2,6,13,22]:hooks.append(net.backbone[i].register_forward_hook(lambda m,i,o:kept.append(o.numel())))
    with torch.inference_mode():out=net(inputs)
    for h in hooks:h.remove()
    conv=[r for r in records if 'macs' in r]
    result=dict(trainable_parameters=sum(p.numel() for p in net.parameters()),conv_weights=sum(r['weights'] for r in conv),
        folded_biases=sum(r['biases'] for r in conv),conv_macs=sum(r['macs'] for r in conv),output=list(out.shape),
        largest_layer_output=max(r['output_elements'] for r in records),full_retained_context_elements=sum(kept),
        max_materialized_input_output_elements=max(math.prod(r['input'])+math.prod(r['output']) for r in records),
        core_materialized_rw_bytes_int8=sum(math.prod(r['input'])+math.prod(r['output']) for r in records),layers=records,lanes={})
    for lanes in [8,16,32]:
        rows=sum(math.ceil(r['channels']/lanes)*r['k'] for r in conv)
        cycles=sum(r['dots']*math.ceil(r['channels']/lanes)*r['k'] for r in conv)
        result['lanes'][str(lanes)]=dict(dot_product_cycles=cycles,ideal_dot_ms_100mhz=cycles/100000,
            height_commuted_dot_cycles=sum((r['dots']//r['output'][2] if r['name'].startswith('container') else r['dots'])*math.ceil(r['channels']/lanes)*r['k'] for r in conv),
            padded_weight_bytes=rows*lanes,banked_weight_ram10=(lanes//2)*math.ceil(rows/512),
            assumption='Each 16-bit ROM bank serves two 8-bit lanes; 512 words per RAM10; pad output channels to lane count; one input broadcast and one MAC/lane/cycle, no stalls. This is a schedule lower bound, not throughput.')
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True);torch.manual_seed(701);torch.set_num_threads(2)
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()=='94a49696268ff942d92d58285ddeacab9b2ef35a4102bd73862518729e0dfc14'
    weight_path=RESEARCH/'lprnet/weights/Final_LPRNet_model.pth'
    assert hashlib.sha256(weight_path.read_bytes()).hexdigest()=='d1ca22ca7a251a90702a166c8ad8ce7f05acb39f5ef8055139a33d462716d1ad'
    spec=importlib.util.spec_from_file_location('source_lprnet',SOURCE);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    original=mod.build_lprnet(class_num=68,phase=False,dropout_rate=0)
    original.load_state_dict(torch.load(RESEARCH/'lprnet/weights/Final_LPRNet_model.pth',map_location='cpu',weights_only=True))
    result={'source68':profile(original,torch.randn(1,3,24,94))}
    assert result['source68']['trainable_parameters']==446976 and result['source68']['conv_macs']==144411264
    for c in [8,16]:result[f'gray_c{c}']=profile(Candidate(c).eval(),torch.randn(1,1,24,94))
    result['gray_c8_native']=profile(Candidate(8,native=True).eval(),torch.randn(1,1,48,160))
    # A 4D tensor is interpreted as unbatched C,D,H,W by MaxPool3d.
    pooling=[]
    for batch in [1,2]:
        x=torch.arange(batch*32*8*22,dtype=torch.float32).reshape(batch,32,8,22)
        for cs,ss in [(1,(1,1)),(2,(1,2)),(4,(1,2))]:
            a=nn.MaxPool3d((1,3,3),(cs,*ss))(x);b=ChannelSpatialPool(cs,ss)(x)
            assert torch.equal(a,b);pooling.append(dict(batch=batch,channel_stride=cs,output=list(a.shape)))
    # The paper's terse 'all pool strides 2x2' is not a runnable patch to this replica.
    naive=mod.build_lprnet(class_num=68,phase=False,dropout_rate=0)
    for i,cs in [(3,1),(7,2),(14,4)]:naive.backbone[i]=nn.MaxPool3d((1,3,3),(cs,2,2))
    try:
        with torch.inference_mode():naive(torch.randn(1,3,24,94))
        raise AssertionError('Expected incompatible head')
    except RuntimeError as e:naive_error=str(e)
    # Evaluate reordering of unchanged pretrained inference; no weight updates.
    original=original.double();max_error=0.;minimum_energy=float('inf')
    for _ in range(3):
        x=torch.randn(1,3,24,94,dtype=torch.float64);branches=[]
        with torch.inference_mode():
            gold=original(x)
            for i,layer in enumerate(original.backbone):
                x=layer(x)
                if i in [2,6,13,22]:branches.append(x)
            for i in [0,1]:branches[i]=F.avg_pool2d(branches[i],5,5)
            branches[2]=F.avg_pool2d(branches[2],(4,10),(4,2))
            weight=original.container[0].weight;bias=original.container[0].bias
            reordered=bias[None,:,None].expand(1,68,18).clone();offset=0
            for f in branches:
                energy=f.square().mean();minimum_energy=min(minimum_energy,float(energy));c=f.shape[1]
                contribution=F.conv2d(f.mean(2,keepdim=True),weight[:,offset:offset+c],bias=None).squeeze(2)/energy
                reordered+=contribution;offset+=c
            error=float((gold-reordered).abs().max());max_error=max(max_error,error);assert error<1e-9
    result['checks']=dict(channel_decimation=pooling,naive_reduced_patch_error=naive_error,
        context_reorder_float64_max_abs_error=max_error,random_inputs=3,minimum_branch_energy=minimum_energy,
        quantized_equivalence=False,training_run=False)
    candidate=Candidate(8,native=True).train()
    before=[p.detach().clone() for p in candidate.parameters()]
    logits=candidate(torch.randn(2,1,48,160))
    target=torch.tensor([0,31,55,55,56,57,58,12,33,59,60,61,61,64])
    loss=nn.CTCLoss(blank=65)(logits.log_softmax(1).permute(2,0,1),target,torch.tensor([35,35]),torch.tensor([7,7]))
    loss.backward();assert torch.isfinite(loss) and all(p.grad is not None and torch.isfinite(p.grad).all() for p in candidate.parameters())
    assert all(torch.equal(a,p) for a,p in zip(before,candidate.parameters()))
    candidate.eval();x=torch.randn(2,1,48,160)
    with torch.inference_mode():
        error=float((candidate(x)-torch.cat([candidate(x[:1]),candidate(x[1:])])).abs().max())
        assert error<1e-5 and torch.isfinite(candidate(torch.zeros_like(x))).all()
    result['checks'].update(ctc_repeated_label_gradient_finite=True,optimizer_steps=0,parameter_values_unchanged=True,
                            candidate_eval_batch_independence_error=error)
    interface=ROOT/'tools/blue_plate/char_model/candidate/interface.json'
    result['student_classes']=json.loads(interface.read_text(encoding='utf8'))['classes']+['<blank>']
    assert len(result['student_classes'])==66
    files=[SOURCE,weight_path,RESEARCH/'lprnet-paper.pdf',interface,Path(__file__)]
    result['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (OUT/'cost.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({k:({a:b for a,b in v.items() if a!='layers'} if isinstance(v,dict) else v)
                      for k,v in result.items() if k!='source_sha256'},indent=2))

if __name__=='__main__':main()
