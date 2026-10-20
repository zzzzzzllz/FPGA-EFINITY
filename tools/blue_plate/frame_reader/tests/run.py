"""Compile immutable input copies and retain commands, return codes and hashes."""
import hashlib
import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from prepare import ROOT, OUT, main as prepare

sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
parser=argparse.ArgumentParser()
parser.add_argument('--tag',default='final')
parser.add_argument('--quick',action='store_true')
args=parser.parse_args()
run=OUT/args.tag
run.mkdir(parents=True,exist_ok=True)
if not (OUT/'oracle.json').exists():
    prepare()
oracle = json.loads((OUT/'oracle.json').read_text())
for name, digest in oracle['sha256'].items():
    assert sha(OUT/name) == digest, name
snapshot = run/'simulation-inputs'
snapshot.mkdir(exist_ok=True)
sources = [ROOT/'tools/blue_plate/frame_reader/rtl/frame_reader.v', Path(__file__).with_name('tb_frame_reader.sv')]
for source in sources:
    shutil.copy2(source, snapshot/source.name)
bin_dir = ROOT/'tools/iverilog-12/app/bin'
commands = [[bin_dir/'iverilog.exe', '-g2012', '-s', 'tb_frame_reader', '-o', run/'test.vvp',
             *[snapshot/p.name for p in sources]],
            [bin_dir/'vvp.exe', '-i', run/'test.vvp', '+WORK='+OUT.as_posix(), *(['+QUICK'] if args.quick else [])]]
result = dict(input_sha256={p.name:sha(snapshot/p.name) for p in sources},
              oracle_sha256=sha(OUT/'oracle.json'), commands=[[str(x) for x in c] for c in commands], stages={})
for stage, command in zip(('compile','run'), commands):
    started=time.monotonic()
    log=run/(stage+'.log')
    with log.open('w') as stream:
        proc=subprocess.run([str(x) for x in command], cwd=OUT, stdout=stream, stderr=subprocess.STDOUT)
    result['stages'][stage]=dict(exit_code=proc.returncode, seconds=round(time.monotonic()-started,3), log_sha256=sha(log))
    if (run/'test.vvp').exists():result['binary_sha256']=sha(run/'test.vvp')
    (run/'execution.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(log.read_text()[-4000:],flush=True)
    if proc.returncode:raise RuntimeError(stage+' failed')
