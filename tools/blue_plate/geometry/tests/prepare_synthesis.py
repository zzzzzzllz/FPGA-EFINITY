"""Prepare isolated full corner-to-ROI synthesis; no shared project changes."""
import hashlib
import argparse
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[4]
parser=argparse.ArgumentParser()
parser.add_argument('--color-output',action='store_true')
args=parser.parse_args()
out=ROOT/('tmp/blue-plate-geometry/color-output/synthesis' if args.color_output else 'tmp/blue-plate-geometry/synthesis')
out.mkdir(parents=True,exist_ok=True)
sources=list((ROOT/'tools/blue_plate/geometry/rtl').glob('*.v'))+list((ROOT/'tools/blue_plate/otsu/rtl').glob('*.v'))
for source in sources:shutil.copy2(source,out/source.name)
if args.color_output:
    top=out/'perspective_quad.v'
    top.write_text(top.read_text().replace('parameter COLOR_OUTPUT=0','parameter COLOR_OUTPUT=1'))
(out/'perspective_quad.sdc').write_text('create_clock -name clk -period 10.000 [get_ports {clk}]\n',encoding='ascii')
design='\n'.join(f'<efx:design_file name="{p.name}" version="default" library="default"/>' for p in sources)
xml=f'''<efx:project xmlns:efx="http://www.efinixinc.com/enf_proj" name="perspective_quad" description="Independent complete perspective ROI pipeline" sw_version="2026.1.132.4.5">
<efx:device_info><efx:family name="Titanium"/><efx:device name="Ti60F225"/><efx:timing_model name="I3"/></efx:device_info>
<efx:design_info def_veri_version="sv_09" def_vhdl_version="vhdl_2008" unified_flow="false">
<efx:top_module name="perspective_quad"/>{design}</efx:design_info>
<efx:constraint_info><efx:sdc_file name="perspective_quad.sdc"/><efx:inter_file name=""/></efx:constraint_info>
<efx:sim_info/><efx:misc_info/><efx:ooc_info/><efx:ip_info/>
<efx:synthesis tool_name="efx_map"><efx:param name="work_dir" value="work_syn" value_type="e_string"/>
<efx:param name="max_threads" value="2" value_type="e_integer"/><efx:param name="retiming" value="0" value_type="e_option"/>
</efx:synthesis></efx:project>'''
(out/'perspective_quad.xml').write_text(xml,encoding='utf8')
(out/'source-hashes.json').write_text(json.dumps({p.name:hashlib.sha256((out/p.name).read_bytes()).hexdigest() for p in sources},indent=2),encoding='utf8')
print(out)
