"""Map only the fixed 16KiB bank and its one-stage link to the frozen MAC."""
from pathlib import Path
import hashlib,json,shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/weight-bank/synthesis'
OUT.mkdir(parents=True,exist_ok=True)
mac=HERE.parent/'mac8/rtl/mac8.v'
assert hashlib.sha256(mac.read_bytes()).hexdigest()=='f3490692d9bd2160144da3c92693bb8b65f0cbe0a9d435dc4321514cd2c7ffee'
for p in (HERE/'rtl/weight_bank8.v',HERE/'rtl/weight_mac8.v',mac):shutil.copy2(p,OUT/p.name)
(OUT/'weight_mac8.sdc').write_text('''create_clock -name clk -period 10.000 [get_ports {clk}]
set_input_delay -clock clk -max 0.000 [get_ports {rst ce wr_en wr_addr* wr_data* issue rd_addr* activation* lane_mask* load seed*}]
set_input_delay -clock clk -min 0.000 [get_ports {rst ce wr_en wr_addr* wr_data* issue rd_addr* activation* lane_mask* load seed*}]
set_output_delay -clock clk -max 0.000 [get_ports {weight_data* read_valid command_error psum* updated* overflow*}]
set_output_delay -clock clk -min 0.000 [get_ports {weight_data* read_valid command_error psum* updated* overflow*}]
''',encoding='ascii')
(OUT/'weight_mac8.xml').write_text('''<efx:project xmlns:efx="http://www.efinixinc.com/enf_proj" name="weight_mac8" description="16KiB synchronous weight bank plus eight MAC lanes" sw_version="2026.1.132.4.5">
<efx:device_info><efx:family name="Titanium"/><efx:device name="Ti60F225"/><efx:timing_model name="I3"/></efx:device_info>
<efx:design_info def_veri_version="sv_09" def_vhdl_version="vhdl_2008" unified_flow="false">
<efx:top_module name="weight_mac8"/>
<efx:design_file name="weight_bank8.v" version="default" library="default"/>
<efx:design_file name="mac8.v" version="default" library="default"/>
<efx:design_file name="weight_mac8.v" version="default" library="default"/>
</efx:design_info><efx:constraint_info><efx:sdc_file name="weight_mac8.sdc"/><efx:inter_file name=""/></efx:constraint_info>
<efx:sim_info/><efx:misc_info/><efx:ooc_info/><efx:ip_info/>
<efx:synthesis tool_name="efx_map">
<efx:param name="work_dir" value="work_syn" value_type="e_string"/>
<efx:param name="write_efx_verilog" value="on" value_type="e_bool"/>
<efx:param name="max_threads" value="2" value_type="e_integer"/>
<efx:param name="mult-auto-pipeline" value="0" value_type="e_option"/>
<efx:param name="retiming" value="0" value_type="e_option"/>
</efx:synthesis></efx:project>''',encoding='utf8')
names=('weight_bank8.v','weight_mac8.v','mac8.v','weight_mac8.sdc','weight_mac8.xml')
(OUT/'input-hashes.json').write_text(json.dumps({name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in names},indent=2)+'\n')
shutil.copy2(OUT/'weight_mac8.xml',OUT/'weight_mac8.before.xml')
print(OUT)
