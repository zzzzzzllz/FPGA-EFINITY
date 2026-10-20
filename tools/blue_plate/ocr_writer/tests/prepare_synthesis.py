"""Prepare an isolated map of the fixed-size OCR HWC writer."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[4]
source=Path(__file__).resolve().parent.parent/'rtl/ocr_hwc_writer.v'
out=ROOT/'tmp/blue-plate-ocr-writer/synthesis'
out.mkdir(parents=True,exist_ok=True)
shutil.copy2(source,out/source.name)
(out/'ocr_hwc_writer.sdc').write_text('create_clock -name clk -period 10.000 [get_ports {clk}]\n')
(out/'ocr_hwc_writer.xml').write_text('''<efx:project xmlns:efx="http://www.efinixinc.com/enf_proj" name="ocr_hwc_writer" description="Fixed OCR HWC writer" sw_version="2026.1.132.4.5">
<efx:device_info><efx:family name="Titanium"/><efx:device name="Ti60F225"/><efx:timing_model name="I3"/></efx:device_info>
<efx:design_info def_veri_version="sv_09" def_vhdl_version="vhdl_2008" unified_flow="false">
<efx:top_module name="ocr_hwc_writer"/><efx:design_file name="ocr_hwc_writer.v" version="default" library="default"/></efx:design_info>
<efx:constraint_info><efx:sdc_file name="ocr_hwc_writer.sdc"/><efx:inter_file name=""/></efx:constraint_info>
<efx:sim_info/><efx:misc_info/><efx:ooc_info/><efx:ip_info/>
<efx:synthesis tool_name="efx_map"><efx:param name="work_dir" value="work_syn" value_type="e_string"/>
<efx:param name="max_threads" value="2" value_type="e_integer"/><efx:param name="retiming" value="0" value_type="e_option"/>
</efx:synthesis></efx:project>''')
(out/'source-hashes.json').write_text(json.dumps({source.name:hashlib.sha256(source.read_bytes()).hexdigest()},indent=2))
print(out)
