"""Prepare exact bit ROMs, simulate against the frozen original, and prepare an isolated map."""
from pathlib import Path
import argparse,hashlib,json,shutil,subprocess,sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/font-compact'
ORIGINAL=ROOT/'tools/blue_plate/plate_display'
SIM=ROOT/'tools/iverilog-12/app/bin';MODELS=Path('D:/Efinity/sim_models/verilog')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    inputs=[ORIGINAL/n for n in ('plate_osd.v','plate_font.mem','plate_defs.vh','assets.json')]
    template_path=ROOT/'tmp/blue-plate-plate-display/synthesis/plate_osd/plate_osd.xml'
    inputs += [template_path,ROOT/'docs/validation/blue-plate/plate-display/plate_osd.map.rpt']
    assets=json.loads((ORIGINAL/'assets.json').read_text(encoding='utf-8'))
    assert sha(ORIGINAL/'plate_font.mem')==assets['rom_sha256']
    words=[int(s,16) for s in (ORIGINAL/'plate_font.mem').read_text().split()]
    assert len(words)==4096 and all(v==0 for v in words[68*32:])
    for p in inputs:shutil.copy2(p,OUT/p.name)
    for name,rows in [('font-low.mem',words[:2048]),('font-high.mem',words[2048:2176])]:
        (OUT/name).write_text(''.join(f'{(row>>(31-x))&1}\n' for row in rows for x in range(32)),encoding='ascii')
    syn=OUT/'synthesis';syn.mkdir(exist_ok=True)
    for p in [HERE/'plate_osd_compact.v',OUT/'plate_defs.vh',OUT/'font-low.mem',OUT/'font-high.mem']:shutil.copy2(p,syn/p.name)
    top='plate_osd_compact'
    (syn/(top+'.sdc')).write_text('create_clock -name clk -period 13.468 [get_ports {clk}]\n')
    template=template_path.read_text()
    template=template.replace('plate_osd','plate_osd_compact')
    (syn/(top+'.xml')).write_text(template,encoding='utf-8')
    shutil.copy2(syn/(top+'.xml'),syn/(top+'.before.xml'))
    result=dict(original_sha256={str(p):sha(p) for p in inputs},source_sha256={str(p):sha(p) for p in HERE.iterdir() if p.is_file()},
                generated_sha256={str(OUT/name):sha(OUT/name) for name in [p.name for p in inputs]+['font-low.mem','font-high.mem']},
                bit_order='address {glyph,row,column}; column 0 equals original row bit 31',font_bits=[65536,4096])
    (OUT/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')


def test(mapped):
    stage='mapped' if mapped else 'rtl'
    inputs=json.loads((OUT/'inputs.json').read_text())
    for paths in ('original_sha256','source_sha256','generated_sha256'):
        for p,h in inputs[paths].items():assert sha(Path(p))==h,p
    sources=[OUT/'plate_osd.v',HERE/'plate_osd_compact.v']
    if mapped:
        net=OUT/'synthesis/out/plate_osd_compact.map.v'
        sys.path.insert(0,str(HERE.parent/'partial_sum'));from lut_startup import prepare as lut_prepare
        sources=[OUT/'plate_osd.v',net,lut_prepare(OUT,MODELS,SIM,net)]
    binary=OUT/(stage+'.vvp')
    cmd=[str(SIM/'iverilog.exe'),'-g2012','-s','tb_font','-I',str(OUT),'-y',str(MODELS),'-Y','.v','-o',str(binary),str(HERE/'tb_font.sv')]+list(map(str,sources))
    p=subprocess.run(cmd,cwd=OUT,capture_output=True,text=True);(OUT/(stage+'-compile.log')).write_text(p.stdout+p.stderr);assert p.returncode==0,p.stderr
    with (OUT/(stage+'-run.log')).open('w') as f:p=subprocess.run([str(SIM/'vvp.exe'),str(binary)],cwd=OUT,stdout=f,stderr=subprocess.STDOUT)
    output=(OUT/(stage+'-run.log')).read_text();assert p.returncode==0 and 'PASS cycles=' in output,output[-4000:]
    for name,h in inputs['original_sha256'].items():assert sha(Path(name))==h,name
    result=dict(stage=stage,stdout=output,original_unchanged=True,files_sha256={str(p):sha(p) for p in sources+[HERE/'tb_font.sv',OUT/'inputs.json',OUT/(stage+'-run.log')]})
    (OUT/(stage+'-validation.json')).write_text(json.dumps(result,indent=2)+'\n');print(output)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','rtl','mapped']);args=ap.parse_args()
    if args.action=='prepare':prepare()
    else:test(args.action=='mapped')
