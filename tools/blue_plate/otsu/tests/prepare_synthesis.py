"""Prepare the standalone Otsu map project; never uses the camera build tree."""
import hashlib
import argparse
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[4]
parser=argparse.ArgumentParser();parser.add_argument('--roi',action='store_true')
args=parser.parse_args()
top='roi_otsu32' if args.roi else 'otsu32'
out=ROOT/'tmp/blue-plate-otsu'/('synthesis-roi' if args.roi else 'synthesis')
out.mkdir(parents=True,exist_ok=True)
shutil.copy2(ROOT/'tools/blue_plate/otsu/rtl/otsu32.v',out/'otsu32.v')
(out/'otsu32.sdc').write_text('create_clock -name clk -period 10.000 [get_ports {clk}]\n',encoding='ascii')
xml='''<efx:project xmlns:efx="http://www.efinixinc.com/enf_proj" name="otsu32" description="Independent exact Otsu core" sw_version="2026.1.132.4.5">
<efx:device_info><efx:family name="Titanium"/><efx:device name="Ti60F225"/><efx:timing_model name="I3"/></efx:device_info>
<efx:design_info def_veri_version="sv_09" def_vhdl_version="vhdl_2008" unified_flow="false">
<efx:top_module name="otsu32"/><efx:design_file name="otsu32.v" version="default" library="default"/>
</efx:design_info><efx:constraint_info><efx:sdc_file name="otsu32.sdc"/><efx:inter_file name=""/></efx:constraint_info>
<efx:sim_info/><efx:misc_info/><efx:ooc_info/><efx:ip_info/>
<efx:synthesis tool_name="efx_map">
<efx:param name="work_dir" value="work_syn" value_type="e_string"/>
<efx:param name="max_threads" value="2" value_type="e_integer"/>
<efx:param name="retiming" value="0" value_type="e_option"/>
</efx:synthesis></efx:project>'''
if args.roi:
    shutil.copy2(ROOT/'tools/blue_plate/otsu/rtl/roi_otsu32.v',out/'roi_otsu32.v')
    xml=xml.replace('name="otsu32"','name="roi_otsu32"')
    xml=xml.replace('</efx:design_info>','<efx:design_file name="roi_otsu32.v" version="default" library="default"/></efx:design_info>')
(out/f'{top}.xml').write_text(xml,encoding='utf8')
(out/'source-hashes.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.suffix in ['.v','.xml','.sdc']},indent=2),encoding='utf8')
print(out)
