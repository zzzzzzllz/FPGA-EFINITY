"""Run existing product regressions against the frozen integration, without hardware."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
import hashlib
HERE=Path(__file__).resolve().parent
PROJECT=HERE.parent
ROOT=PROJECT.parents[1]
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
SIM=ROOT/'tools/iverilog-12/app/bin'
LOG=ROOT/'tmp/tests'/PROJECT.name/'regression';LOG.mkdir(parents=True,exist_ok=True)
RESULT=[]
RESUME=False
STORE_ONLY=False

def run(name,args):
    previous=next((r for r in RESULT if r['name']==name and r['returncode']==0),None)
    if RESUME and previous and sha(HERE/previous['log'])==previous['sha256']:
        print('REUSE completed',name,flush=True);return
    RESULT[:]=[r for r in RESULT if r['name']!=name]
    start=time.time();p=LOG/(name+'.log')
    print('START',name,flush=True)
    with p.open('w') as out:r=subprocess.run([str(a) for a in args],cwd=PROJECT,stdout=out,stderr=subprocess.STDOUT)
    text=p.read_text();print(text[-1800:],flush=True)
    RESULT.append(dict(name=name,returncode=r.returncode,seconds=round(time.time()-start,3),log=str(p),sha256=sha(p)))
    (LOG/(GROUP+'.json')).write_text(json.dumps(RESULT,indent=2))
    if r.returncode:raise RuntimeError(name+' failed; see '+str(p))

def py(name,*args):run(name+('-'+'-'.join(a.lstrip('-') for a in args) if args else ''),[sys.executable,'-B',HERE/'tools'/f'{name}.py',*args])
def rtl(top,files,defines=(),options=()):
    name=top+('+'+'+'.join(defines) if defines else '')
    exe=LOG/(name+'.vvp')
    run(name+'-compile',[SIM/'iverilog.exe','-g2012',*[f'-D{d}' for d in defines],'-I',PROJECT/'rtl','-s','tb_'+top,'-o',exe,*options,*[PROJECT/'rtl'/(f+'.v') for f in files],PROJECT/'tests'/('tb_'+top+'.v')])
    run(name,[SIM/'vvp.exe','-i',exe])

STORE=['frame_store','frame_store_control','frame_store_dma','frame_pair_fifo','frame_mailbox','frame_buffer_V4/DC_FIFO']
DISPLAY=['frame_store_dma','frame_buffer_V4/DC_FIFO','user_cvo_axi_v2/cvo_axi_v2','compare_display','threshold_osd']

def main():
    if GROUP=='small':
        rtl('canny_rules',['gaussian_pair','sobel_pair','canny_nms_pair'])
        for name in ('local','denoise','hysteresis','store','faults'):py('test-canny-'+name)
        py('test-canny-hysteresis','--medium');py('test-canny-store','--medium','--shape')
        for top,files in [('frame_memory_probe',['frame_memory_probe']),('frame_store_control',['frame_store_control']),('frame_reference_header',STORE),('frame_store',STORE)]:rtl(top,files)
        rtl('frame_store',STORE+['median_pair','sobel_pair'],['REAL_ALGORITHM'])
        for top in ('edge_ui','threshold_control','threshold_osd','compare_display'):
            rtl(top,['edge_ui','threshold_control','threshold_osd','compare_display'])
        rtl('gamma_rom',['gamma_conrrection/gamma_correction','true_dual_port_ram'],options=[PROJECT/'tests/tb_gamma_baseline.v'])
        rtl('debug_status_snapshot',['debug_status_snapshot']);rtl('shape_overlay',['threshold_osd'])
        py('test-sensor-control');py('test-paged-status')
        rtl('o1_i2c',['cam_i2c_ctrl/i2c/i2c_16addr_8data'])
        rtl('o1_sensor',['cam_i2c_ctrl/i2c/i2c_master_ctrl_top','cam_i2c_ctrl/i2c/i2c_master_reg_set','cam_i2c_ctrl/i2c/i2c_master_reg_rom'])
        rtl('o1_response_cdc',['ti60f225_oob_top'],options=['-i'])
    elif GROUP=='full':
        py('test-canny-store','--full','--shape','--target')
        rtl('frame_store',STORE+['median_pair','sobel_pair'],['REAL_ALGORITHM','FULL_SMOKE'])
        if not STORE_ONLY:
            for defines in ([],['CANNY_DISPLAY'],['CANNY_DISPLAY','REFERENCE_DISPLAY']):rtl('frame_display',DISPLAY,defines)
    elif GROUP=='shape':
        py('test-shape-components');py('test-shape-reference')
        py('test-shape-rtl');py('test-shape-rtl','--stress');py('test-shape-rtl','--validation')
    elif GROUP.startswith('display_'):
        defines={'display_sobel':[],'display_canny':['CANNY_DISPLAY'],'display_reference':['CANNY_DISPLAY','REFERENCE_DISPLAY']}[GROUP]
        rtl('frame_display',DISPLAY,defines)
    else:raise ValueError(GROUP)
    print('PASS',GROUP,len(RESULT),'commands',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('group',choices=('small','full','shape','display_sobel','display_canny','display_reference'));p.add_argument('--resume',action='store_true')
    p.add_argument('--store-only',action='store_true')
    args=p.parse_args();GROUP=args.group;RESUME=args.resume;STORE_ONLY=args.store_only
    if GROUP.startswith('display_'):
        LOG=ROOT/'tmp/tests'/PROJECT.name/('regression-'+GROUP);LOG.mkdir(parents=True,exist_ok=True)
    if RESUME:RESULT=json.loads((LOG/(GROUP+'.json')).read_text())
    main()
