"""Run protocol tests and independently check every rendered OSD pixel."""
import hashlib
import json
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OUT=ROOT/'tmp/blue-plate-plate-display';DOC=ROOT/'docs/validation/blue-plate/plate-display'


def main():
    OUT.mkdir(exist_ok=True)
    assets=json.loads((HERE/'assets.json').read_text(encoding='utf8'));classes=assets['classes']
    def encode(s):return sum(classes.index(c)<<(7*i) for i,c in enumerate(s))
    (OUT/'test_ids.vh').write_text(f"`define TEST_A 49'h{encode('皖A43Y26'):013x}\n`define TEST_B 49'h{encode('粤B12345'):013x}\n",encoding='ascii')
    provinces=[c for c in classes if not c.isascii()];letters=[c for c in classes if c.isascii() and c.isalpha()];alnum=[c for c in classes if c.isascii()]
    samples=[c+letters[f%len(letters)]+''.join(alnum[(f*5+k)%len(alnum)] for k in range(5)) for f,c in enumerate(provinces)]
    samples[0]='皖A43Y26';samples[19]='粤B12345'
    assert set(''.join(samples))==set(classes)
    (OUT/'plate_ids.mem').write_text(''.join(f'{encode(s):013x}\n' for s in samples)+f'{0:013x}\n',encoding='ascii')
    binpath=ROOT/'tools/iverilog-12/app/bin';logs={}
    for test,sources,half in [('plate_state',['plate_confirm.v','plate_mailbox.v','plate_display_state.v'],h) for h in [3,7,11]]+[('plate_osd',['plate_osd.v'],None)]:
        name=test+(f'-dst{half}' if half else '')
        exe=OUT/(name+'.vvp')
        command=[str(binpath/'iverilog.exe'),'-g2012','-Wall','-I',str(HERE),'-I',str(OUT),'-s','tb_'+test,'-o',str(exe)]+[str(HERE/s) for s in sources]+[str(HERE/('tb_'+test+'.sv'))]
        if half:command.insert(1,f'-Ptb_plate_state.DST_HALF={half}')
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True);logs[name+'_compile']=result.stdout+result.stderr
        if result.returncode:raise RuntimeError(logs[name+'_compile'])
        result=subprocess.run([str(binpath/'vvp.exe'),str(exe)],cwd=ROOT,capture_output=True,text=True,timeout=120)
        logs[name]=result.stdout+result.stderr
        (OUT/(name+'.log')).write_text(logs[name],encoding='utf8')
        print(logs[name],flush=True)
        if result.returncode:raise RuntimeError(test+' failed')
    actual=np.array(Image.open(OUT/'osd.ppm'))
    rom=np.array([int(s,16) for s in (HERE/'plate_font.mem').read_text().splitlines()],np.uint32).reshape(128,32)
    expected=np.empty((2560,320,3),np.uint8);expected[:]=[38,56,73]
    for f in range(32):
        expected[f*80+16:f*80+64,16:272]=[18,59,120]
        chars=samples[f] if f<31 else '  未识别  '
        for pos,c in enumerate(chars):
            glyph=assets['glyphs'].index(c)
            mask=((rom[glyph,:,None]>>np.arange(31,-1,-1,dtype=np.uint32))&1).astype(bool)
            tile=expected[f*80+24:f*80+56,32+pos*32:64+pos*32];tile[mask]=255
    assert actual.shape==expected.shape
    mismatch=int(np.any(actual!=expected,axis=2).sum());assert mismatch==0,mismatch
    preview=np.concatenate([actual[:80],actual[19*80:20*80],actual[31*80:32*80]])
    Image.fromarray(preview).resize((640,480),Image.Resampling.NEAREST).save(DOC/'osd-preview.png')
    evidence=dict(logs=logs,rendered_pixels=819200,pixel_mismatches=mismatch,rendered_class_count=len(set(''.join(samples))),synthetic_samples=samples,scope='Synthetic protocol and display verification only; no real recognition claim',
        sources_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir() if p.is_file()},
        assets=assets)
    (OUT/'verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    (DOC/'verification.json').write_text((OUT/'verification.json').read_text(encoding='utf8'),encoding='utf8')
    print('PASS independent pixel reference:',actual.shape,'mismatches=0',flush=True)


if __name__=='__main__':main()
