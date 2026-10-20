"""Read-only shape/resource audit. Synthetic input only; no training or synthesis."""
from pathlib import Path
import ast
import csv
import hashlib
import importlib.util
import json
import math
import re
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'tmp/blue-plate-whole-plate-budget'
DOC = ROOT/'docs/validation/blue-plate/whole-plate-budget'
MODEL = ROOT/'tmp/blue-plate-review/mature-research/lprnet/model/LPRNet.py'
REPORTS = {
 'video':'docs/validation/blue-plate/video-base/evidence/live-map.rpt',
 'reader':'docs/validation/blue-plate/frame-reader/evidence/frame_reader.map.rpt',
 'geometry':'tmp/blue-plate-geometry/synthesis/out/perspective_quad.map.rpt',
 'display':'docs/validation/blue-plate/plate-display/plate_display.map.rpt',
 'old_classifier':'docs/validation/blue-plate/char-model/geometry11.map.rpt',
 'old_preprocess':'docs/validation/blue-plate/char-preprocess/evidence/char_preprocess.map.rpt'}


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    DOC.mkdir(parents=True,exist_ok=True)
    paths=[MODEL,MODEL.parents[1]/'data/load_data.py',*[ROOT/p for p in REPORTS.values()],
           ROOT/'docs/validation/blue-plate/video-base/evidence/live-place.rpt',
           ROOT/'tmp/blue-plate-normal-g1/mature-detector/resource-audit.json',
           ROOT/'tmp/blue-plate-normal-g1/mature-detector/model-costs.json',
           Path('D:/Efinity/sim_models/verilog/efx_ram10.v')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    resources={}
    for name,rel in REPORTS.items():
        text=(ROOT/rel).read_text(errors='replace').split('Resource Summary (begin)')[1]
        resources[name]={k:int(v) for k,v in re.findall(r'^(EFX_\w+)\s*:\s*(\d+)',text,re.M)}
    retained=['reader','geometry','display']
    add=lambda key:sum(resources[n].get(key,0) for n in retained)
    lut,ff,adder=add('EFX_LUT4'),add('EFX_FF'),add('EFX_ADD')
    resources['budget']={'limits':{'XLR':49248,'RAM10':204,'DSP':128},
       'video_placed':{'XLR':24090,'RAM10':106,'DSP':85},
       'retained_ram':106+add('EFX_RAM10'), 'retained_dsp':85+add('EFX_DSP48'),
       'new_map_totals':{'LUT4':lut,'FF':ff,'ADD':adder},
       'xlr_remaining_ideal_cross_module_pack':49248-24090-max(lut+adder,ff),
       'xlr_remaining_ideal_module_local_pack':49248-24090-sum(max(resources[n]['EFX_LUT4']+resources[n]['EFX_ADD'],resources[n]['EFX_FF']) for n in retained),
       'xlr_remaining_no_ff_pack':49248-24090-lut-adder-ff,
       'xlr_scope':'packing envelope for unchanged mapped primitives; not PNR or guaranteed bounds after optimization/routing'}
    spec=importlib.util.spec_from_file_location('audited_existing_lprnet',MODEL)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    tree=ast.parse(paths[1].read_text(encoding='utf8'))
    chars=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='CHARS' for t in n.targets))
    torch.set_num_threads(1);torch.manual_seed(617)
    net=module.build_lprnet(7,False,len(chars),0)
    rows=[];pool_checks=[]
    def hook(name):
        def record(m,inputs,output):
            inp=inputs[0];r={'name':name,'type':type(m).__name__, 'input':list(inp.shape),'output':list(output.shape)}
            if isinstance(m,torch.nn.Conv2d):
                k=m.in_channels*math.prod(m.kernel_size)
                for axis in range(2):
                    assert output.shape[axis+2]==(inp.shape[axis+2]+2*m.padding[axis]-m.kernel_size[axis])//m.stride[axis]+1
                r.update(kernel=list(m.kernel_size),weights=m.weight.numel(),bias=m.out_channels,
                         K=k,positions=output.shape[2]*output.shape[3],macs=output.numel()*k,
                         input_bytes=inp.numel(),output_bytes=output.numel(),
                         full_channel_line_bytes=(m.kernel_size[0]-1)*inp.shape[3]*m.in_channels)
            else:
                s=m.stride
                equivalent=F.max_pool2d(inp[:,::s[0]],kernel_size=(3,3),stride=s[1:])
                assert torch.equal(output,equivalent)
                r.update(kernel=list(m.kernel_size),stride=list(s),
                         selected_input_bytes=inp[:,::s[0]].numel(),output_bytes=output.numel())
                pool_checks.append(name)
            rows.append(r)
        return record
    for n,m in net.named_modules():
        if isinstance(m,(torch.nn.Conv2d,torch.nn.MaxPool3d)):m.register_forward_hook(hook(n))
    with torch.inference_mode():logits=net(torch.randn(1,3,24,94))
    conv=[r for r in rows if r['type']=='Conv2d'];pools=[r for r in rows if r['type']=='MaxPool3d']
    macs=sum(r['macs'] for r in conv);weights=sum(r['weights'] for r in conv);bias=sum(r['bias'] for r in conv)
    assert macs==144411264 and sum(p.numel() for p in net.parameters())==446976
    # Four context branches have the observed output geometry [channels,4,18].
    contexts=[{'channels':c,'elements':c*4*18,'max_int8_square_sum':c*4*18*128**2} for c in (64,128,256,68)]
    context_input=64*22*92+128*20*90+256*18*44
    context_bytes=sum(r['elements'] for r in contexts)
    pool_traffic=sum(r['selected_input_bytes']+r['output_bytes'] for r in pools)
    # All intermediate operations spill; BN/ReLU fused, context normalization on final read.
    ancillary=pool_traffic+context_input+context_bytes+68*18*4
    conv_once=sum(r['input_bytes']+r['output_bytes']+r['weights']+12*r['bias'] for r in conv)
    schedules=[]
    for pe in (16,32):
        activation=weight_traffic=output=compute=psum=0
        details=[]
        for r in conv:
            groups=math.ceil(r['output'][1]/pe);spatial=r['positions'];k=r['K']
            a=spatial*k*groups
            w=math.ceil(spatial/16)*k*groups*pe
            # Serialized load/save of PE int32 accumulators at each K tile; conservative.
            cycles=a;ps=spatial*groups*math.ceil(k/512)*2*pe
            activation+=a;weight_traffic+=w;output+=r['output_bytes'];compute+=cycles;psum+=ps
            details.append({'name':r['name'],'activation_payload':a,'weight_payload':w,'compute_cycles':cycles,'psum_cycles':ps})
        total=activation+weight_traffic+output+12*bias+ancillary
        schedules.append({'PE':pe,'S':16,'Ktile':512,'activation_payload':activation,'weight_payload':weight_traffic,
          'output_payload':output,'other_payload':12*bias+ancillary,'total_payload_bytes':total,
          'uncached_16byte_activation_beats_total':16*activation+weight_traffic+output+12*bias+ancillary,
          'one_16byte_beat_per_nonweight_byte_ceiling':16*(total-weight_traffic)+weight_traffic,
          'compute_cycles':compute,'psum_serial_cycles':psum,'output_requant_serial_cycles':output,
          'arithmetic_schedule_ms':(compute+psum+output)/100000,
          'ideal_mac_ms':macs/(pe*100000),'details':details})
    widths=[]
    for alpha in (1,0.5,0.25):
        total=0;w=0;b=0
        for r in conv:
            ci=r['input'][1];co=r['output'][1]
            if r['name']=='container.0':ci=int(448*alpha)+68
            elif r['name']!='backbone.0':ci=int(ci*alpha)
            if r['name'] not in ('backbone.20','container.0'):co=int(co*alpha)
            count=ci*co*math.prod(r['kernel']);w+=count;b+=co;total+=count*r['positions']
        widths.append({'hidden_width_multiplier':alpha,'macs':total,'int8_weights_int32_bias_bytes':w+4*b,
                       'scope':'analytic same-spatial-geometry sketch only; no new model or accuracy claim'})
    hyper=json.loads(paths[-3].read_text())
    comparisons={name:{'macs':r['total_macs'],'weight_bias_bytes':r['int8_weights_int32_bias_bytes'],
        'ms_39DSP_1MAC':r['total_macs']/3900000,'ms_39DSP_dual_ceiling':r['total_macs']/7800000,
        'ms_32DSP_1MAC':r['total_macs']/3200000} for name,r in hyper.items() if isinstance(r,dict) and 'total_macs' in r}
    allocations=[]
    for pe in (16,32):
        ram={'weight_pingpong_512deep':2*math.ceil(pe*8/20),
             'serial_int32_partial_sums':2,'activation_cache_8KiB':8,
             'axi128_read_write_buffers':14,'bias_multiplier_shift':4,'int32_logits':6}
        allocations.append({'PE':pe,'RAM10':ram,'total_RAM10':sum(ram.values()),
                            'DSP_MAC':pe,'DSP_requant_allowance':4,'total_DSP':pe+4,
                            'RAM10_remaining':73-sum(ram.values()),'DSP_remaining':39-pe-4,
                            'scope':'Analytic allocation only; excludes locator and unmapped integration logic; XLR not established'})
    result={'resources':resources,'lprnet':{'classes':len(chars),'trainable_parameters':446976,'conv_macs':macs,
       'conv_weights':weights,'conv_biases':bias,'int8_weights_int32_bias_bytes':weights+4*bias,
       'with_int32_multiplier_shift_bytes':weights+12*bias,'max_output_elements':max(r['output_bytes'] for r in conv),
       'logits_shape':list(logits.shape),'layers':rows,'contexts':contexts,
       'serial_nonconv':{'maxpool_comparisons':sum(r['output_bytes']*8 for r in pools),
          'context_average_additions':64*72*24+128*72*24+256*72*39,
          'context_squares':context_bytes,'context_sum_additions':context_bytes-4,
          'context_rescale_multiplications':context_bytes},
       'compulsory_external_weights_input_logits_bytes':weights+12*bias+6768+4896,
       'one_read_per_operator_spill_payload_bytes':conv_once+ancillary,'schedules':schedules,'width_sketches':widths},
       'engine_allocations':allocations,
       'hyperlpr_cost_correction':comparisons,'checks':{'shape_formula':True,'pool_channel_decimation_exact':pool_checks,
       'source_unchanged':all(hashlib.sha256(p.read_bytes()).hexdigest()==hashes[str(p)] for p in paths)},
       'source_sha256':hashes,'scope':'No accuracy evaluation, model training, new CNN implementation, synthesis or board access'}
    assert result['checks']['source_unchanged']
    (OUT/'costs.json').write_text(json.dumps(result,indent=2)+'\n')
    (DOC/'costs.json').write_text(json.dumps(result,indent=2)+'\n')
    with (DOC/'layers.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['name','input_CxHxW','output_CxHxW','K','MACs','weight_elements','line_buffer_int8_bytes'])
        for r in conv:writer.writerow([r['name'],'x'.join(map(str,r['input'][1:])),'x'.join(map(str,r['output'][1:])),r['K'],r['macs'],r['weights'],r['full_channel_line_bytes']])
    print(json.dumps({k:result[k] for k in ('resources','hyperlpr_cost_correction','checks')},indent=2))
    print('LPRNet', {k:v for k,v in result['lprnet'].items() if k not in ('layers','schedules','contexts')})
    print('Schedules', [{k:v for k,v in r.items() if k!='details'} for r in schedules])


if __name__=='__main__':main()
