"""Create an isolated map project with real input and output ports."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'tmp/blue-plate-frame-reader/synthesis'
OUT.mkdir(parents=True,exist_ok=True)
rtl=ROOT/'tools/blue_plate/frame_reader/rtl/frame_reader.v'
shutil.copy2(rtl,OUT/rtl.name)
(OUT/'frame_reader.sdc').write_text('create_clock -name clk -period 10.000 [get_ports {clk}]\n',encoding='ascii')
(OUT/'frame_reader.xml').write_text('''<efx:project xmlns:efx="http://www.efinixinc.com/enf_proj" name="frame_reader" description="Independent held raw-frame burst reader" sw_version="2026.1.132.4.5">
<efx:device_info><efx:family name="Titanium"/><efx:device name="Ti60F225"/><efx:timing_model name="I3"/></efx:device_info>
<efx:design_info def_veri_version="sv_09" def_vhdl_version="vhdl_2008" unified_flow="false">
<efx:top_module name="frame_reader"/><efx:design_file name="frame_reader.v" version="default" library="default"/>
</efx:design_info><efx:constraint_info><efx:sdc_file name="frame_reader.sdc"/><efx:inter_file name=""/></efx:constraint_info>
<efx:sim_info/><efx:misc_info/><efx:ooc_info/><efx:ip_info/>
<efx:synthesis tool_name="efx_map">
<efx:param name="work_dir" value="work_syn" value_type="e_string"/>
<efx:param name="write_efx_verilog" value="on" value_type="e_bool"/>
<efx:param name="max_threads" value="2" value_type="e_integer"/>
<efx:param name="mult-auto-pipeline" value="0" value_type="e_option"/>
<efx:param name="retiming" value="0" value_type="e_option"/>
</efx:synthesis></efx:project>''',encoding='utf8')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
inputs={p.name:sha(p) for p in OUT.iterdir() if p.suffix in ('.v','.sdc','.xml')}
(OUT/'input-hashes.json').write_text(json.dumps(inputs,indent=2)+'\n',encoding='utf8')
provenance=OUT/'provenance';provenance.mkdir(exist_ok=True)
shutil.copy2(OUT/'frame_reader.xml',provenance/'frame_reader.before.xml')
shutil.copy2(OUT/'input-hashes.json',provenance/'input-hashes.before.json')
print(OUT)
