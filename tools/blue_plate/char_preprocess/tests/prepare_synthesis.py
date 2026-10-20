"""Prepare an isolated Efinity project with live top-level streaming ports."""
import json
import shutil
import hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'tmp/blue-plate-char-preprocess'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

out=OUT/'synthesis';out.mkdir(parents=True,exist_ok=True)
rtl=ROOT/'tools/blue_plate/char_preprocess/rtl/char_preprocess.v'
shutil.copy2(rtl,out/rtl.name)
(out/'char_preprocess.sdc').write_text('create_clock -name clk -period 10.000 [get_ports {clk}]\n',encoding='ascii')
(out/'char_preprocess.xml').write_text('''<efx:project xmlns:efx="http://www.efinixinc.com/enf_proj" name="char_preprocess" description="Isolated raw ROI normalization and features" sw_version="2026.1.132.4.5">
<efx:device_info><efx:family name="Titanium"/><efx:device name="Ti60F225"/><efx:timing_model name="I3"/></efx:device_info>
<efx:design_info def_veri_version="sv_09" def_vhdl_version="vhdl_2008" unified_flow="false">
<efx:top_module name="char_preprocess"/><efx:design_file name="char_preprocess.v" version="default" library="default"/>
</efx:design_info><efx:constraint_info><efx:sdc_file name="char_preprocess.sdc"/><efx:inter_file name=""/></efx:constraint_info>
<efx:sim_info/><efx:misc_info/><efx:ooc_info/><efx:ip_info/>
<efx:synthesis tool_name="efx_map">
<efx:param name="work_dir" value="work_syn" value_type="e_string"/>
<efx:param name="write_efx_verilog" value="on" value_type="e_bool"/>
<efx:param name="max_threads" value="2" value_type="e_integer"/>
<efx:param name="use-logic-for-small-rom" value="0" value_type="e_integer"/>
<efx:param name="mult-auto-pipeline" value="0" value_type="e_option"/>
<efx:param name="retiming" value="0" value_type="e_option"/>
</efx:synthesis></efx:project>''',encoding='utf8')
(out/'input-hashes.json').write_text(json.dumps({p.name:sha(p) for p in out.iterdir() if p.suffix in ['.v','.sdc','.xml']},indent=2)+'\n',encoding='utf8')
provenance=out/'provenance';provenance.mkdir(exist_ok=True)
shutil.copy2(out/'char_preprocess.xml',provenance/'char_preprocess.before.xml')
shutil.copy2(out/'input-hashes.json',provenance/'input-hashes.before.json')
print(out)
