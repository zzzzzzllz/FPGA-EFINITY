"""Isolated blue-mask mapping, using the same ROMs as the exhaustive test."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[4]
out = ROOT/'tmp/blue-plate-locator/synthesis-blue'
out.mkdir(parents=True, exist_ok=True)
sources = [ROOT/'tools/blue_plate/locator/rtl/blue_hs_filter.v']
sources += [ROOT/'tmp/blue-plate-locator/blue-mask'/f'{name}.mem'
            for name in ['blue_saturation', 'blue_hue']]
for source in sources:
    shutil.copy2(source, out/source.name)
(out/'blue_hs_filter.sdc').write_text('create_clock -name clk -period 10.000 [get_ports {clk}]\n', encoding='ascii')
(out/'blue_hs_filter.xml').write_text('''<efx:project xmlns:efx="http://www.efinixinc.com/enf_proj" name="blue_hs_filter" description="Exact blue H/S predicate" sw_version="2026.1.132.4.5">
<efx:device_info><efx:family name="Titanium"/><efx:device name="Ti60F225"/><efx:timing_model name="I3"/></efx:device_info>
<efx:design_info def_veri_version="sv_09" def_vhdl_version="vhdl_2008" unified_flow="false">
<efx:top_module name="blue_hs_filter"/><efx:design_file name="blue_hs_filter.v" version="default" library="default"/></efx:design_info>
<efx:constraint_info><efx:sdc_file name="blue_hs_filter.sdc"/><efx:inter_file name=""/></efx:constraint_info>
<efx:sim_info/><efx:misc_info/><efx:ooc_info/><efx:ip_info/>
<efx:synthesis tool_name="efx_map"><efx:param name="work_dir" value="work_syn" value_type="e_string"/>
<efx:param name="max_threads" value="2" value_type="e_integer"/><efx:param name="retiming" value="0" value_type="e_option"/>
</efx:synthesis></efx:project>''', encoding='utf8')
(out/'source-hashes.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                                               for p in sources}, indent=2), encoding='utf8')
print(out)
