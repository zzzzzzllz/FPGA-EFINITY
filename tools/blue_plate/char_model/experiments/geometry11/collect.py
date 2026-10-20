"""Freeze successful default, signed11, boundary and mapped verification."""
import re
import shutil
from run import ROOT,MODEL,HERE,OUT,BASE,DOC,read,save,sha,candidate_hashes,EXPECTED


def main():
    config=read(HERE/'interface.json');assert candidate_hashes()==config['candidate_hashes']
    assert sha(BASE/'frozen-domain/geometry/weights.npz')==EXPECTED
    current={str(p.relative_to(ROOT)):sha(p) for p in [MODEL/'rtl/char_linear.v',MODEL/'tests/tb_char_linear.sv']}
    results={}
    default=read(BASE/'rtl/simulation.json')
    for key,value in current.items():assert default['hashes'][key.replace('\\','/')]==value
    assert 'PASS vectors=159 compared_scores=10465 latency_cycles=41796' in default['result']
    results['default']=dict(vectors=159,scores=10465,latency_cycles=41796)
    shutil.copy2(BASE/'rtl/simulation.json',DOC/'geometry11-default-regression.json')
    for name,count,scores in [('rtl',320,20930),('boundary10',36,2470),('boundary',36,2470),('mapped',9,715)]:
        p=OUT/name/'simulation.json';record=read(p)
        assert record['source_hashes']==current,(name,'source drift')
        assert f'PASS vectors={count} compared_scores={scores} latency_cycles=41796' in record['result']
        if name in ['rtl','mapped']:assert record['rom_roundtrip']==config['roundtrip']
        if name=='mapped':assert record['mapped_netlist_sha256']==sha(OUT/'synthesis/out/geometry11_char_linear.map.v')
        results[name]=dict(vectors=count,scores=scores,latency_cycles=41796,record_sha256=sha(p))
        shutil.copy2(p,DOC/f'geometry11-{name}-simulation.json')
    assert all(r['rejected'] for r in read(OUT/'guard/verification.json').values())
    shutil.copy2(OUT/'guard/verification.json',DOC/'geometry11-invalid-widths.json')
    report=OUT/'synthesis/out/geometry11_char_linear.map.rpt';text=report.read_text()
    resources={name:int(value) for name,value in re.findall(r'^(EFX_\w+)\s+:\s+(\d+)',text,re.M)}
    assert resources['EFX_RAM10']==36 and resources['EFX_DSP48']==1
    for name in ['char_linear.v','geometry11_char_linear.v','w1-s11.bin','b1.mem']:
        source=MODEL/'rtl'/name if name=='char_linear.v' else HERE/name
        assert sha(source)==sha(OUT/'synthesis'/name)
    assert report.stat().st_mtime>=max(p.stat().st_mtime for p in (OUT/'synthesis').glob('*.v'))
    shutil.copy2(report,DOC/'geometry11.map.rpt')
    shutil.copy2(OUT/'synthesis/out/geometry11_char_linear.res.csv',DOC/'geometry11.res.csv')
    review=ROOT/'tmp/blue-plate-review/geometry11/review-result.json'
    for path,value in read(review)['source_sha256'].items():assert sha(ROOT/path)==value
    shutil.copy2(review,DOC/'geometry11-independent-review.json')
    save(DOC/'geometry11-hardware.json',dict(source_weights_sha256=EXPECTED,candidate_unchanged=True,candidate_hashes=config['candidate_hashes'],
        core_and_tb_sha256=current,experiment_files_sha256={p.name:sha(p) for p in HERE.iterdir() if p.is_file()},rom_roundtrip=config['roundtrip'],
        thresholds=config['thresholds'],absolute_accumulator_bound=config['absolute_accumulator_bound'],tests=results,resources=resources,
        map_report_sha256=sha(report),map_netlist_sha256=sha(OUT/'synthesis/out/geometry11_char_linear.map.v'),
        scope='Independent geometry model arithmetic/protocol/map verification; no heldout scoring, shared top, PNR, hardware operation or formal candidate replacement'))
    print('Frozen results:',results);print('Mapped resources:',resources)


if __name__=='__main__':main()
