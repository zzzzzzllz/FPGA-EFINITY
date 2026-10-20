"""Prepare an isolated map of the fixed-size OCR input converter."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[4]
source=Path(__file__).resolve().parent.parent/'rtl/ocr_resize_q8.v'
out=ROOT/'tmp/blue-plate-ocr-input/synthesis'
out.mkdir(parents=True,exist_ok=True)
shutil.copy2(source,out/source.name)
(out/'ocr_resize_q8.sdc').write_text('create_clock -name clk -period 10.000 [get_ports {clk}]\n')
(out/'ocr_resize_q8.xml').write_text('''<efx:project xmlns:efx="http://www.efinixinc.com/enf_proj" name="ocr_resize_q8" description="Fixed Q8 OCR input" sw_version="2026.1.132.4.5">
<efx:device_info><efx:family name="Titanium"/><efx:device name="Ti60F225"/><efx:timing_model name="I3"/></efx:device_info>
<efx:design_info def_veri_version="sv_09" def_vhdl_version="vhdl_2008" unified_flow="false">
<efx:top_module name="ocr_resize_q8"/><efx:design_file name="ocr_resize_q8.v" version="default" library="default"/></efx:design_info>
<efx:constraint_info><efx:sdc_file name="ocr_resize_q8.sdc"/><efx:inter_file name=""/></efx:constraint_info>
<efx:sim_info/><efx:misc_info/><efx:ooc_info/><efx:ip_info/>
<efx:synthesis tool_name="efx_map"><efx:param name="work_dir" value="work_syn" value_type="e_string"/>
<efx:param name="max_threads" value="2" value_type="e_integer"/><efx:param name="retiming" value="0" value_type="e_option"/>
</efx:synthesis></efx:project>''')
(out/'source-hashes.json').write_text(json.dumps({source.name:hashlib.sha256(source.read_bytes()).hexdigest()},indent=2))
print(out)
