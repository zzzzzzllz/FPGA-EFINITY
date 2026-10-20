"""Verify scalar-read evidence and update only the independent candidate budget."""
from pathlib import Path
import hashlib,json,re,shutil
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/scalar-read'
DOC=ROOT/'docs/validation/blue-plate/whole-plate-budget'


def main():
    tracked={};sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    def read(p):
        tracked[str(p)]=sha(p);return json.loads(p.read_text())
    def verify(hashes):
        for name,h in hashes.items():
            p=Path(name);p=p if p.is_absolute() else ROOT/p
            assert sha(p)==h,name
    freeze=read(ROOT/'tmp/blue-plate-whole-plate-budget/requant-static/delivery-freeze.json')
    verify(freeze['files_sha256'])
    original=read(DOC/'requant-validation.json')
    verify({p:h for p,h in original['files_sha256'].items() if p.startswith('tools') or p.endswith(('.map.v','.map.rpt'))})
    baseline=read(DOC/'requant-static-validation.json');verify(baseline['files_sha256'])
    old=baseline['resources']
    proof=read(ROOT/'tmp/blue-plate-whole-plate-budget/requant-static/proof-and-schedule.json')
    inputs=read(OUT/'test-inputs.json');verify(inputs['source_sha256'])
    results={}
    for stage in ('rtl','mapped'):
        for bench in ('psum','scalar'):
            name=stage+'-'+bench;r=read(OUT/(name+'-validation.json'))
            assert r['exit_code']==0;verify(r['files_sha256']);results[name]=r['stdout'].splitlines()[-2:]
    lut=read(OUT/'lut-startup-validation.json');verify(lut['files_sha256']);assert lut['exit_code']==0
    mapped=read(OUT/'synthesis/synthesis-summary.json');verify(mapped['files_sha256']);assert mapped['exit_code']==0
    assert mapped['resources']['EFX_RAM10']==18 and mapped['resources']['EFX_DSP48']==8
    research=read(OUT/'research/sources.json');assert sha(Path(research['local_model']['path']))==research['local_model']['sha256']
    maps=dict(old['maps']);maps['shared_q31']=mapped['resources']
    comb=sum(r.get('EFX_LUT4',0)+r.get('EFX_ADD',0) for r in maps.values())
    ff=sum(r.get('EFX_FF',0) for r in maps.values())
    xlr=dict(ideal_cross_module_ff_pack=old['video_placed_XLR']+max(comb,ff),
        ideal_module_local_ff_pack=old['video_placed_XLR']+sum(max(r.get('EFX_LUT4',0)+r.get('EFX_ADD',0),r.get('EFX_FF',0)) for r in maps.values()),
        no_ff_pack=old['video_placed_XLR']+comb+ff)
    assert (comb,ff)==(21976,10322)
    resources={**old,'maps':maps,'added_comb_slots':comb,'added_FF':ff,'conditional_XLR':xlr,
        'remaining_XLR':{k:old['budget']['XLR']-v for k,v in xlr.items()}}
    rows=[dict(name=r['name'],dynamic_primary_outputs=r['dynamic_outputs'],old_restore_cycles=17*r['dynamic_outputs'],
        new_read_overhead_cycles=2*r['dynamic_outputs'],saved_cycles=15*r['dynamic_outputs']) for r in proof['rows'] if r['name']!='tap2.trunk']
    count=sum(r['dynamic_primary_outputs'] for r in rows);saved=sum(r['saved_cycles'] for r in rows)
    assert count==702480 and saved==10537200
    service=dict(dynamic_primary_outputs=count,standalone_read_cycles=3,combined_dynamic_transaction_cycles=29,
        old_restore_plus_dynamic_transaction_cycles=44,saved_cycles=saved,
        previous_lpr_core_cycles=proof['new_lpr_core_cycles'],new_lpr_core_cycles=proof['new_lpr_core_cycles']-saved,
        previous_known_three_model_cycles=proof['new_known_three_model_cycles'],new_known_three_model_cycles=proof['new_known_three_model_cycles']-saved,
        scope='Per-transaction timings verified on RTL and mapped; network totals projected. Existing K-split restores, dense MAC, all saves and prior omitted costs remain.',rows=rows)
    for p in HERE.rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:tracked[str(p)]=sha(p)
    report=DOC/'scalar-read-implementation.md';tracked[str(report)]=sha(report)
    for name in ('rtl-psum-validation.json','rtl-scalar-validation.json','mapped-psum-validation.json','mapped-scalar-validation.json','lut-startup-validation.json','test-inputs.json'):
        dest=DOC/('scalar-read-'+name);shutil.copyfile(OUT/name,dest);tracked[str(dest)]=sha(dest)
    result=dict(status='PASS independent scalar interface + Q31 candidate; mapped requires documented local LUT startup adaptation',
        frozen_static_candidate_unchanged=True,original_mac_bank_unchanged=True,resources=resources,
        map_delta=mapped['increment_over_frozen_static_q31'],tests=results,input_coverage=inputs['inserted'],
        real_q_outputs=inputs['real_q_outputs'],real_fork_outputs=inputs['real_fork_outputs'],real_mac_steps=inputs['real_mac_steps'],
        lut_checks=lut['checks'],service=service,research=research,
        timing='10ns constraint; map only, no PNR/100MHz STA, no DDR or board integration.',files_sha256=tracked)
    receipt=DOC/'scalar-read-validation.json'
    receipt.write_text(json.dumps(result,indent=2)+'\n')
    frozen_files={**tracked,str(receipt):sha(receipt)}
    (OUT/'delivery-freeze.json').write_text(json.dumps(dict(status='Standalone candidate complete; ready for independent review; no PNR/network claim',files_sha256=frozen_files),indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','map_delta','tests','lut_checks','timing')},indent=2))
    print(json.dumps({k:v for k,v in service.items() if k!='rows'},indent=2))
    print(json.dumps(resources,indent=2))


if __name__=='__main__':main()
