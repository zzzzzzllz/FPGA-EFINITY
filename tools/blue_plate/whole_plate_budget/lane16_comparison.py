"""Bounded 8/16-lane audit from frozen graph evidence; no RTL or model export."""
from pathlib import Path
import csv,hashlib,importlib.util,json,math,re
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
DOC=ROOT/'docs/validation/blue-plate/whole-plate-budget'
OUT=ROOT/'tmp/blue-plate-whole-plate-budget'


def align(n):return (n+15)//16*16


def labels(path):
    return {m[1]:m[2] for m in re.finditer(r'^\s*"([^"]+)" \[label="([^\n]+)" fillcolor',path.read_text(),re.M)}


def geometry(label):
    stride=tuple(map(int,re.search(r'stride \(HxW\): (\d+) x (\d+)',label).groups()))
    pads=tuple(map(int,re.search(r'pad \(HxW\): \((\d+), (\d+)\) x \((\d+), (\d+)\)',label).groups()))
    return stride,(pads[0],pads[2])


def main():
    source=ROOT/'tmp/blue-plate-review/mature-research/lprnet/model/LPRNet.py'
    files=[DOC/'detector-sharing.json',DOC/'full-lprnet-sharing.json',DOC/'color-cnn-sharing.json',
        DOC/'color-model-cost.json',DOC/'costs.json',
        ROOT/'tmp/blue-plate-normal-g1/mature-detector/model-costs.json',
        OUT/'detector320.dot',OUT/'color-model.dot',source,
        Path('D:/Efinity/sim_models/verilog/efx_ram_10k.v')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    det,lpr,col,ccost,costs,models=[json.loads(p.read_text()) for p in files[:6]]
    spec=importlib.util.spec_from_file_location('lane16_lpr',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    net=module.build_lprnet(7,False,68,0)
    graphs=[]
    for model,rows,dot in [('detector',models['detector320']['layers'],labels(files[6])),
                            ('color',ccost['layers'],labels(files[7]))]:
        for r in rows:
            if r['type'] not in ('Convolution','Gemm'):continue
            co=r['blobs'][0][0];k=math.prod(r['blobs'][0][1:])
            conv=r['type']=='Convolution'
            ci=r['inputs'][0][1];dw=conv and ci//r['blobs'][0][1]>1
            if dw:assert ci==co and r['blobs'][0][1]==1
            stride,pad=geometry(dot[r['name']]) if conv else ((1,1),(0,0))
            graphs.append(dict(model=model,name=r['name'],ci=ci,co=co,K=k,dw=dw,
                input=r['inputs'][0][2:] if conv else [1,1],
                output=r['outputs'][0][2:] if conv else [1,1],
                kernel=r['blobs'][0][2:] if conv else [1,1],stride=stride,pad=pad,
                output_width=4 if r['name']=='onnx_node!Gemm_103' else 1))
    for r in costs['lprnet']['layers']:
        if r['type']!='Conv2d' or r['name']=='container.0':continue
        layer=net.get_submodule(r['name'])
        graphs.append(dict(model='lpr',name=r['name'],ci=r['input'][1],co=r['output'][1],
            K=r['K'],dw=False,input=r['input'][2:],output=r['output'][2:],
            kernel=layer.kernel_size,stride=layer.stride,pad=layer.padding,output_width=1))
    for c in lpr['contexts']:
        graphs.append(dict(model='lpr',name=f"context.{c['tap']}",ci=c['channels'],co=68,
            K=c['channels'],dw=False,input=[1,18],output=[1,18],
            kernel=[1,1],stride=[1,1],pad=[0,0],output_width=4,context=True))
    schedule=[]
    for lanes in (8,16):
        for g in graphs:
            co=g['co'];k=g['K'];groups=math.ceil(co/lanes);positions=math.prod(g['output'])
            limit=16384//lanes
            chunks=[min(limit,k-start) for start in range(0,k,limit)]
            tile=min(16,4096//(co*g['output_width']),positions)
            # Context accumulates directly into the dedicated logits banks.
            if g.get('context'):tile=min(16,positions)
            packed=align(groups*k*lanes) if g['dw'] else groups*sum(align(ch*lanes) for ch in chunks)
            wreads=packed if g['dw'] else math.ceil(positions/tile)*packed
            metadata=align(co*9)
            # The four context branches share the one container bias/scale table.
            if g.get('context') and g['name']!='context.2':metadata=0
            meta_reads=metadata*(math.ceil(positions/tile) if co>512 else 1)
            ih,iw=g['input'];oh,ow=g['output'];kh,kw=g['kernel'];sy,sx=g['stride'];py,px=g['pad']
            valid_taps=sum(0<=oy*sy+ky-py<ih and 0<=ox*sx+kx-px<iw
                for oy in range(oh) for ox in range(ow) for ky in range(kh) for kx in range(kw))
            crossing=0
            if g['dw']:
                for oy in range(oh):
                    for ox in range(ow):
                        for ky in range(kh):
                            for kx in range(kw):
                                iy,ix=oy*sy+ky-py,ox*sx+kx-px
                                if not (0<=iy<ih and 0<=ix<iw):continue
                                for ch in range(0,co,lanes):
                                    count=min(lanes,co-ch);start=(iy*iw+ix)*co+ch
                                    assert 0<=start<start+count<=ih*iw*co
                                    crossing+=((start+count-1)//16-start//16)
                reads=valid_taps*groups+crossing
            else:
                reads=valid_taps*g['ci']*groups
            # Inputs to Gemm have one spatial element and K scalar channels.
            if g['name']=='onnx_node!Gemm_101':assert reads==k*groups
            steps=positions*groups*k
            pswords=2*positions*groups*lanes*(len(chunks)-1)
            psbytes=tile*lanes*4 if len(chunks)>1 else 0
            assert psbytes<=2048 and max(chunks)*lanes<=16384
            schedule.append(dict(model=g['model'],name=g['name'],lanes=lanes,depthwise=g['dw'],
                channels=co,K=k,positions=positions,groups=groups,invalid_tail_lanes=(-co)%lanes,
                K_chunks=chunks,spatial_tile=tile,mac_steps=steps,valid_input_word_reads=reads,
                cross_word_vectors=crossing,partial_sum_bytes=psbytes,partial_sum_word_actions=pswords,
                weight_storage=packed,weight_reads=wreads,metadata_storage=metadata,metadata_reads=meta_reads,
                serial_hit_mac_actions=steps+2*reads+pswords,
                largest_weight_chunk_bytes=max(chunks)*lanes))
    summary={}
    for lanes in (8,16):
        by_model={}
        for model in ('detector','lpr','color'):
            r=[r for r in schedule if r['lanes']==lanes and r['model']==model]
            by_model[model]={key:sum(x[key] for x in r) for key in (
                'mac_steps','valid_input_word_reads','cross_word_vectors','partial_sum_word_actions',
                'weight_storage','weight_reads','metadata_storage','metadata_reads','serial_hit_mac_actions')}
            by_model[model]['mac_ms_100MHz']=by_model[model]['mac_steps']/100000
            by_model[model]['serial_hit_mac_ms_100MHz']=by_model[model]['serial_hit_mac_actions']/100000
        summary[str(lanes)]=by_model
        d,l,c=[by_model[x] for x in ('detector','lpr','color')]
        summary[str(lanes)]['totals']={f'{n}_roi':{
            'mac_ms_100MHz':(d['mac_steps']+n*(l['mac_steps']+c['mac_steps']))/100000,
            'serial_hit_mac_ms_100MHz':(d['serial_hit_mac_actions']+n*(l['serial_hit_mac_actions']+c['serial_hit_mac_actions']))/100000,
            'weight_reads':d['weight_reads']+n*(l['weight_reads']+c['weight_reads']),
            'metadata_reads':d['metadata_reads']+n*(l['metadata_reads']+c['metadata_reads']),
            'MAC_input_all_miss_read_bytes':16*(d['valid_input_word_reads']+n*(l['valid_input_word_reads']+c['valid_input_word_reads'])),
        } for n in (1,2)}
    assert summary['8']['detector']['mac_steps']==22977600
    assert summary['8']['lpr']['mac_steps']==lpr['timing']['mac_steps']
    assert summary['8']['color']['mac_steps']==col['macs']['shared8_mac_steps']
    assert summary['8']['lpr']['weight_reads']==lpr['timing']['weight_read_bytes']
    assert summary['8']['color']['weight_reads']==col['traffic']['weight_reads']
    assert summary['8']['detector']['weight_reads']==11388880
    # Same sixteen RAMs, now eight 16-bit width banks with two 512-row depth groups.
    rng=np.random.default_rng(1616);checks=[]
    for k,valid in ((3328,16),(3328,4),(1280,16)):
        a=rng.integers(-255,256,(16,k),dtype=np.int64)
        w=rng.integers(-127,128,(valid,k),dtype=np.int64)
        gold=a@w.T;acc=np.zeros((16,16),dtype=np.int64)
        ps=np.zeros(512,dtype=np.int32)
        for start in range(0,k,1024):
            end=min(k,start+1024);padded=np.zeros((16,end-start),dtype=np.int64);padded[:valid]=w[:,start:end]
            banks=np.zeros((8,2,512),dtype=np.uint16)
            words=(padded[::2]&255)|((padded[1::2]&255)<<8)
            banks.reshape(8,1024)[:,:end-start]=words
            packed=banks.reshape(8,1024)[:,:end-start]
            restored=np.empty_like(padded);restored[::2]=packed&255;restored[1::2]=packed>>8
            restored[restored>=128]-=256
            assert np.array_equal(restored,padded)
            if start:acc=ps[:256].reshape(16,16).astype(np.int64)
            acc+=a[:,start:end]@restored.T
            assert np.abs(acc).max()<2**31
            if end<k:ps[:256]=acc.reshape(-1)
        assert np.array_equal(acc[:,:valid],gold)
        checks.append(dict(K=k,valid_lanes=valid,exact_outputs=gold.size,psum_bytes=1024,weight_RAM=16))
    reserve_old=[det['traffic']['padded_weight_storage'],lpr['memory']['padded_int8_weight_storage'],col['memory']['packed_weights']]
    reserve_new=[max(old,summary['16'][model]['weight_storage']) for old,model in zip(reserve_old,('detector','lpr','color'))]
    result=dict(source_sha256=hashes,source_unchanged=all(hashlib.sha256(p.read_bytes()).hexdigest()==hashes[str(p)] for p in files),
        schedule=schedule,summary=summary,bank_and_split_checks=checks,
        memory=dict(weight_bank_8={'width_banks':4,'depth_groups':4,'shape':'2048x64'},
                    weight_bank_16={'width_banks':8,'depth_groups':2,'shape':'1024x128'},
                    weight_RAM=16,shared_RAM_target=51,full_RAM_target=196,full_DSP_8=97,full_DSP_16=105,
                    fixed_budget={'XLR':49248,'RAM10':204,'physical_DSP':128},
                    previous_weight_reserves=reserve_old,lane16_weight_reserves=reserve_new,
                    lane16_total_ddr_reserve=col['memory']['full_three_model_ddr_reservation']+sum(reserve_new)-sum(reserve_old)),
        scope='MAC loops and explicitly serialized tag/data/MAC hit-path schedule. No cache-miss trace, cycle RTL, XLR, DDR service, quantization or display changes.')
    assert result['source_unchanged'] and result['memory']['lane16_total_ddr_reserve']<=8*1024*1024
    for folder in (DOC,OUT):(folder/'lane16-comparison.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    with (DOC/'lane16-layers.csv').open('w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=list(schedule[0]));writer.writeheader();writer.writerows(schedule)
    print(json.dumps({k:v for k,v in result.items() if k not in ('schedule','source_sha256')},indent=2))


if __name__=='__main__':main()
