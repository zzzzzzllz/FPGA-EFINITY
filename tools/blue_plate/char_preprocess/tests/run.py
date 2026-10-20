"""Run deterministic RTL comparisons against frozen raw ROIs and edge cases."""
import argparse
import json
import re
import shutil
import subprocess
import time
from prepare import ROOT,MODEL,OUT,prepare,prepare_empty,sha

def main(e2e,stalls,empty):
    manifest_path=OUT/('empty-vectors.json' if empty else 'vectors.json')
    manifest=prepare_empty() if empty else (json.loads(manifest_path.read_text(encoding='utf8')) if manifest_path.exists() else prepare())
    for rel,digest in manifest['source_sha256'].items():assert sha(ROOT/rel)==digest,rel
    rtl=ROOT/'tools/blue_plate/char_preprocess/rtl/char_preprocess.v'
    tb=ROOT/'tools/blue_plate/char_preprocess/tests/tb_char_preprocess.sv'
    sim=ROOT/'tools/iverilog-12/app/bin'
    for rom in ['w1-s10.bin','b1.mem']:
        if not (OUT/rom).exists():shutil.copy2(MODEL/'candidate'/rom,OUT/rom)
        assert sha(MODEL/'candidate'/rom)==sha(OUT/rom)
    name=('e2e' if e2e else 'preprocess')+('-stalls' if stalls else '')+('-empty' if empty else '')
    snapshot=OUT/(name+'-inputs');snapshot.mkdir(exist_ok=True)
    for source in [rtl,tb,*([MODEL/'rtl/char_linear.v'] if e2e else [])]:shutil.copy2(source,snapshot/source.name)
    frozen_rtl=snapshot/rtl.name;frozen_tb=snapshot/tb.name
    exe=OUT/(name+'.vvp')
    commands=[[sim/'iverilog.exe','-g2012','-s','tb_char_preprocess','-o',exe,
               *(['-DEND_TO_END'] if e2e else []),frozen_rtl,frozen_tb,*([snapshot/'char_linear.v'] if e2e else [])],
              [sim/'vvp.exe','-i',exe,*(['+STALLS'] if stalls else []),*(['+CASEFILE=cases-empty.txt'] if empty else [])]]
    result={}
    for stage,command in zip(['compile','run'],commands):
        log=OUT/(name+'-'+stage+'.log');start=time.monotonic()
        with log.open('w') as stream:p=subprocess.run([str(x) for x in command],cwd=OUT,stdout=stream,stderr=subprocess.STDOUT)
        print(log.read_text()[-1800:],flush=True)
        if p.returncode:raise RuntimeError(f'{stage} failed: {log}')
        result[stage+'_seconds']=round(time.monotonic()-start,3)
    text=(OUT/(name+'-run.log')).read_text()
    metrics=[dict(case=int(a),error=int(b),preprocess_cycles=int(c),total_cycles=int(d)) for a,b,c,d in
             re.findall(r'CASE (\d+) error=(\d+) preprocess_cycles=(\d+) total_cycles=(\d+)',text)]
    assert len(metrics)==len(manifest['cases'])+3 and 'PASS ' in text
    for rel,digest in manifest['source_sha256'].items():assert sha(ROOT/rel)==digest,rel
    result.update(end_to_end=e2e,stalls=stalls,metrics=metrics,real_rois=manifest['real_raw_rois'],
                  cases=len(manifest['cases']),exact=True,source_unchanged=True,
                  rtl_sha256=sha(frozen_rtl),testbench_sha256=sha(frozen_tb),vectors_sha256=sha(manifest_path),
                  commands=[[str(x) for x in command] for command in commands],exit_codes=[0,0])
    (OUT/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print('PASS',name,len(metrics),'completed jobs; all reference hashes unchanged',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--e2e',action='store_true');parser.add_argument('--stalls',action='store_true');parser.add_argument('--empty',action='store_true')
    args=parser.parse_args();main(args.e2e,args.stalls,args.empty)
