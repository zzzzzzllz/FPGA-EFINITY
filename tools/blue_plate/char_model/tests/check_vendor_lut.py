"""Reproduce the stock EFX_LUT4/Icarus time-zero issue and verify the local fix."""
import hashlib
import json
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'tmp/blue-plate-char-model/rtl-mapped'
OUT.mkdir(parents=True,exist_ok=True)
source=Path('D:/Efinity/sim_models/verilog/efx_lut4.v')
old='always @(I0_net or I1_net or I2_net or I3_net) begin'
content=source.read_text();assert content.count(old)==1
adapted=OUT/'efx_lut4_icarus.v'
adapted.write_text(content.replace(old,'always_comb begin'),encoding='utf8')
bin_dir=ROOT/'tools/iverilog-12/app/bin'
report={}
for name,model in [('original',source),('adapted',adapted)]:
    exe=OUT/(name+'-lut.vvp')
    compile_result=subprocess.run([str(bin_dir/'iverilog.exe'),'-g2012','-s','tb_vendor_lut_init','-o',str(exe),str(model),str(Path(__file__).with_name('tb_vendor_lut_init.sv'))],capture_output=True,text=True)
    assert compile_result.returncode==0,compile_result.stderr
    result=subprocess.run([str(bin_dir/'vvp.exe'),str(exe)],capture_output=True,text=True)
    (OUT/(name+'-lut.log')).write_text(result.stdout+result.stderr,encoding='utf8')
    report[name]=dict(exit_code=result.returncode,output=result.stdout,model_sha256=hashlib.sha256(model.read_bytes()).hexdigest())
assert report['original']['exit_code']!=0 and 'output=0 expected=1' in report['original']['output']
assert report['adapted']['exit_code']==0 and '64 truth-table entries' in report['adapted']['output']
(OUT/'vendor-lut-check.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps(report,indent=2))
