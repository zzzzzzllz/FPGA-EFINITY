"""Prepare a standalone map-only project without touching the camera project."""
import hashlib
import json
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[4]
MODEL=ROOT/'tools/blue_plate/char_model'
out=ROOT/'tmp/blue-plate-char-model/synthesis'
out.mkdir(parents=True,exist_ok=True)
for source,name in [(MODEL/'rtl/char_linear.v','char_linear.v'),(MODEL/'candidate/w1-s10.bin','w1-s10.bin'),(MODEL/'candidate/b1.mem','b1.mem')]:
    shutil.copy2(source,out/name)
(out/'char_linear.sdc').write_text('create_clock -name clk -period 10.000 [get_ports {clk}]\n',encoding='ascii')
(out/'char_linear.xml').write_text('''<efx:project xmlns:efx="http://www.efinixinc.com/enf_proj" name="char_linear" description="Isolated character classifier synthesis" sw_version="2026.1.132.4.5">
<efx:device_info><efx:family name="Titanium"/><efx:device name="Ti60F225"/><efx:timing_model name="I3"/></efx:device_info>
<efx:design_info def_veri_version="sv_09" def_vhdl_version="vhdl_2008" unified_flow="false">
<efx:top_module name="char_linear"/><efx:design_file name="char_linear.v" version="default" library="default"/>
</efx:design_info><efx:constraint_info><efx:sdc_file name="char_linear.sdc"/><efx:inter_file name=""/></efx:constraint_info>
<efx:sim_info/><efx:misc_info/><efx:ooc_info/><efx:ip_info/>
<efx:synthesis tool_name="efx_map">
<efx:param name="work_dir" value="work_syn" value_type="e_string"/>
<efx:param name="max_threads" value="2" value_type="e_integer"/>
<efx:param name="use-logic-for-small-rom" value="0" value_type="e_integer"/>
<efx:param name="mult-auto-pipeline" value="0" value_type="e_option"/>
<efx:param name="retiming" value="0" value_type="e_option"/>
</efx:synthesis></efx:project>''',encoding='utf8')
(out/'source-hashes.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.suffix in ['.v','.mem','.bin','.xml','.sdc']},indent=2),encoding='utf8')
print(out)
