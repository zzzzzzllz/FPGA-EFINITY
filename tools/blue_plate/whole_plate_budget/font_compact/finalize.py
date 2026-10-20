"""Verify physical ROM modes/initialization, equivalence results, and freeze this candidate."""
from collections import Counter
from pathlib import Path
import hashlib,json,re,xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/font-compact'
DOC=ROOT/'docs/validation/blue-plate/whole-plate-budget'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def resources(path):
    s=path.read_text().split('Resource Summary (begin)',1)[1].split('Resource Summary (end)',1)[0]
    return {k:int(v) for k,v in re.findall(r'^(EFX_\w+)\s*:\s*(\d+)',s,re.M)}


def main():
    inputs=json.loads((OUT/'inputs.json').read_text())
    for group in ('original_sha256','source_sha256','generated_sha256'):
        for p,h in inputs[group].items():assert sha(Path(p))==h,p
    syn=OUT/'synthesis';net=syn/'out/plate_osd_compact.map.v'
    for name in ('plate_osd_compact.v','plate_defs.vh','font-low.mem','font-high.mem'):
        original=HERE/name if name.endswith('.v') else OUT/name
        assert sha(original)==sha(syn/name),name
    def semantic(n):return n.tag,sorted(n.attrib.items()),(n.text or '').strip(),[semantic(c) for c in n]
    assert semantic(ET.parse(syn/'plate_osd_compact.xml').getroot())==semantic(ET.parse(syn/'plate_osd_compact.before.xml').getroot())
    old=resources(ROOT/'docs/validation/blue-plate/plate-display/plate_osd.map.rpt')
    new=resources(syn/'out/plate_osd_compact.map.rpt')
    assert new['EFX_RAM10']==9 and not any(new.get(k,0) for k in ('EFX_DSP48','EFX_DSP24','EFX_DSP12'))
    data=net.read_text();cells=re.findall(r'^\s*EFX_RAM10\s+(\S+)\s+\(',data,re.M)
    assert len(cells)==9
    low=[int(v) for v in (OUT/'font-low.mem').read_text().split()]
    high=[int(v) for v in (OUT/'font-high.mem').read_text().split()]
    expected=[sum(b<<i for i,b in enumerate(low[start:start+8192])) for start in range(0,65536,8192)]
    expected_high=sum(b<<i for i,b in enumerate(high));actual=[];params={}
    for cell in cells:
        values=dict(re.findall(r'defparam\s+'+re.escape(cell)+r'\s*\.(\w+)\s*=\s*([^;]+);',data))
        required={'READ_WIDTH':'1','WRITE_WIDTH':'1','OUTPUT_REG':"1'b0",'RESET_RAM':'"ASYNC"'}
        assert all(values.get(k)==v for k,v in required.items()),cell
        bits=sum(int(values['INIT_'+format(i,'X')].split("'h")[1],16)<<(256*i) for i in range(40))
        assert bits>>8192==0,cell
        if cell=='font_high':assert bits==expected_high
        else:actual.append(bits)
        params[cell]=dict(**required,init_sha256=hashlib.sha256(bits.to_bytes(1280,'little')).hexdigest(),ones=bits.bit_count())
    assert Counter(actual)==Counter(expected)
    assert re.search(r'map\s*:\s*PASS',(syn/'map.console.log').read_text())
    validation={stage:json.loads((OUT/(stage+'-validation.json')).read_text()) for stage in ('rtl','mapped')}
    for stage,v in validation.items():
        assert 'PASS cycles=981712 reset_checks=58' in v['stdout']
        for p,h in v['files_sha256'].items():assert sha(Path(p))==h,p
    lut=json.loads((OUT/'lut-startup-validation.json').read_text())
    for p,h in lut['files_sha256'].items():assert sha(Path(p))==h,p
    freeze_counts={}
    for name in ('requant-static','scalar-read'):
        frozen=json.loads((ROOT/f'tmp/blue-plate-whole-plate-budget/{name}/delivery-freeze.json').read_text())['files_sha256']
        for p,h in frozen.items():assert sha(ROOT/p)==h,p
        freeze_counts[name]=len(frozen)
    result=dict(status='Standalone RTL/map candidate verified; not integrated or placed/routed',
                original=old,candidate=new,delta={k:new.get(k,0)-old.get(k,0) for k in sorted(set(old)|set(new))},
                original_unchanged=True,physical_ROMs=params,initialization_exact=True,
                equivalence=dict(RTL_cycles=981712,mapped_cycles=981712,reset_checks_each=58,latency_cycles=1,
                                 incoming_IDs=128,slots=7,independent_pixel_reference=True),
                mapped_simulation_condition=dict(local_vendor_LUT_startup_fix=True,validated_masks=lut['unique_masks'],truth_checks=lut['checks']),
                timing='13.468ns clock constraint, map only; no PNR timing result',
                full_firmware=dict(previous_direct_addition_RAM=232,conditional_replacement_RAM=225,remaining_RAM_deficit=21,
                                   previous_full_plan_RAM=264,conditional_full_plan_RAM=257,full_plan_deficit=53,
                                   integrated_XLR=None,scope='Subtract standalone 7-RAM delta only; combined integration not measured'),
                prior_frozen_files_verified=freeze_counts)
    for folder in (OUT,DOC):
        (folder/'font-compact-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    paths=[p for p in HERE.rglob('*') if p.is_file()]+[p for p in OUT.rglob('*') if p.is_file() and p.name!='delivery-freeze.json']
    paths += [Path(p) for p in inputs['original_sha256']]
    paths += [DOC/'font-compact-validation.json',DOC/'font-compact-implementation.md',ROOT/'tools/blue_plate/whole_plate_budget/partial_sum/lut_startup.py',MODELS/'efx_lut4.v',MODELS/'efx_ram10.v']
    frozen={str(p):sha(p) for p in paths}
    (OUT/'delivery-freeze.json').write_text(json.dumps(dict(status=result['status'],files_sha256=frozen),indent=2)+'\n')
    assert all(sha(Path(p))==h for p,h in frozen.items())
    print(json.dumps(dict(resources=new,delta=result['delta'],frozen_files=len(frozen),lut=lut['checks']),indent=2))


MODELS=Path('D:/Efinity/sim_models/verilog')
if __name__=='__main__':main()
