"""Verify existing receipts and combine the candidate with the actual OCR map."""
from pathlib import Path
import hashlib,json,re,shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/requant-static'
DOC=ROOT/'docs/validation/blue-plate/whole-plate-budget'


def main():
    tracked={}
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    def read(p):
        tracked[str(p.relative_to(ROOT))]=sha(p)
        return json.loads(p.read_text())
    def verify(hashes):
        for name,expected in hashes.items():
            p=Path(name)
            if not p.is_absolute():p=ROOT/p
            assert sha(p)==expected,str(p)
    proof=read(OUT/'proof-and-schedule.json')
    verify(proof['source_sha256'])
    assert all(0<p['multiplier']<(1<<31) and 1<=p['shift']<=62 for p in proof['proofs'])
    deployment=read(ROOT/'tmp/blue-plate-char-segment/deployment-roi0/manifest.json')
    qrows={r['output']:r for r in deployment['requantization']}
    for r in proof['rows']:
        assert qrows[r['name']]['output_elements']==r['constant_outputs']+r['dynamic_outputs']
    context_outputs=sum(r['output_elements'] for n,r in qrows.items() if n.startswith('context.'))
    assert context_outputs==37152 and sum(r['output_elements'] for r in qrows.values())==1413728
    service=read(DOC/'service-cost.json')
    verify(service['source_sha256'])
    receipts={}
    for label,name in [('rtl','rtl-validation.json'),('mapped','mapped-validation.json'),('lut','lut-startup-validation.json'),('map','synthesis/synthesis-summary.json')]:
        r=read(OUT/name);assert r['exit_code']==0;verify(r['files_sha256']);receipts[label]=r
    baseline=read(DOC/'requant-validation.json')
    # Keep every source and the frozen Q31 netlist/report unchanged.
    verify({p:h for p,h in baseline['files_sha256'].items() if p.startswith('tools') or p.endswith(('.map.v','.map.rpt'))})
    research=read(ROOT/'tmp/blue-plate-review/service-research/research-record.json')
    verify({str(ROOT/'tmp/blue-plate-review/service-research'/r['file']):r['sha256'] for r in research['files']})
    ocrpath=ROOT/'tmp/blue-plate-ocr-input/synthesis/out/ocr_resize_q8.map.rpt'
    tracked[str(ocrpath.relative_to(ROOT))]=sha(ocrpath)
    ocr={k:int(v) for k,v in re.findall(r'^(EFX_\w+)\s*:\s*(\d+)\s*$',ocrpath.read_text(),re.M)}
    assert {k:ocr[k] for k in ('EFX_LUT4','EFX_FF','EFX_ADD','EFX_RAM10')}==dict(EFX_LUT4=520,EFX_FF=339,EFX_ADD=96,EFX_RAM10=1)
    assert ocr.get('EFX_DSP48',0)==0
    old=service['resources'];maps=dict(old['maps'])
    maps['shared_q31']=receipts['map']['resources'];maps['ocr_resize']=ocr
    comb=sum(r.get('EFX_LUT4',0)+r.get('EFX_ADD',0) for r in maps.values())
    ff=sum(r.get('EFX_FF',0) for r in maps.values())
    xlr=dict(ideal_cross_module_ff_pack=old['video_placed_XLR']+max(comb,ff),
        ideal_module_local_ff_pack=old['video_placed_XLR']+sum(max(r.get('EFX_LUT4',0)+r.get('EFX_ADD',0),r.get('EFX_FF',0)) for r in maps.values()),
        no_ff_pack=old['video_placed_XLR']+comb+ff)
    engine_ram=maps['shared_q31']['EFX_RAM10']+ocr['EFX_RAM10']
    mapped_ram=old['mapped_RAM10']-old['maps']['shared_q31']['EFX_RAM10']+engine_ram
    ram=mapped_ram+old['external_gray_allocation']+old['engine_target_RAM10']-engine_ram
    dsp=old['full_target_DSP']-old['maps']['shared_q31']['EFX_DSP48']+maps['shared_q31']['EFX_DSP48']
    assert (comb,ff,ram,dsp)==(21885,10321,196,97)
    resources=dict(budget=old['budget'],video_placed_XLR=old['video_placed_XLR'],maps=maps,
        added_comb_slots=comb,added_FF=ff,conditional_XLR=xlr,
        remaining_XLR={k:old['budget']['XLR']-v for k,v in xlr.items()},mapped_RAM10=mapped_ram,
        external_gray_allocation=old['external_gray_allocation'],engine_target_RAM10=old['engine_target_RAM10'],
        engine_mapped_RAM10=engine_ram,engine_unmapped_RAM10=old['engine_target_RAM10']-engine_ram,
        full_target_RAM10=ram,full_target_DSP=dsp,
        scope='Conditional packing arithmetic, not PNR bounds. Replaces frozen Q31; OCR RAM uses the existing resize allocation. Excludes unmapped logic.')
    stats={}
    for label in ('rtl','mapped'):
        m=re.search(r'cases=(\d+) constants=(\d+) cycles=(\d+) stalls=(\d+)',receipts[label]['stdout']);assert m
        stats[label]=dict(zip(('cases','constants','cycles','stalls'),map(int,m.groups())))
    result=dict(status='Full-int8 proof, RTL, bounded mapped with local LUT startup adaptation, and map PASS',
        constant_outputs=proof['constant_outputs'],constant_channels=sum(p['constant'] for p in proof['proofs']),
        six_stage_round_checks=proof['six_stage_round_checks'],tests=stats,lut_checks=receipts['lut']['checks'],
        map=maps['shared_q31'],map_delta=receipts['map']['increment_over_frozen_q31'],
        service={k:proof[k] for k in ('old_lpr_core_cycles','new_lpr_core_cycles','old_known_three_model_cycles','new_known_three_model_cycles','total_saved_cycles','constant_transaction_cycles')},
        deployment_counts=dict(q31_outputs=proof['constant_outputs']+proof['dynamic_outputs'],context_wide_gain_outputs=context_outputs,all_requantized_outputs=1413728),
        resources=resources,frozen_baseline_unchanged=True,
        scope='Independent candidate, not integrated. Per-transaction cycles verified; network cycle totals projected. No DDR/board/PNR test; 100MHz is a conversion assumption. Current 500ms/3-confirm contract is unchanged and is not a user hard requirement.',
        research=research,files_sha256=tracked)
    for p in HERE.rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:tracked[str(p.relative_to(ROOT))]=sha(p)
    report=DOC/'requant-static-implementation.md'
    tracked[str(report.relative_to(ROOT))]=sha(report)
    for name in ('proof-and-schedule.json','rtl-validation.json','mapped-validation.json','lut-startup-validation.json'):
        shutil.copyfile(OUT/name,DOC/('requant-static-'+name))
    (DOC/'requant-static-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('files_sha256','research','resources')},indent=2))
    print(json.dumps(resources,indent=2))


if __name__=='__main__':main()
