from pathlib import Path
import hashlib,json,shutil,xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/scalar-read/synthesis'
OUT.mkdir(parents=True,exist_ok=True)
sources=[HERE/'rtl/q31_scalar_mac8.v',HERE/'rtl/psum_scalar_mac8.v',HERE.parent/'mac8/rtl/mac8.v',HERE.parent/'weight_bank/rtl/weight_bank8.v',HERE.parent/'weight_bank/rtl/weight_mac8.v']
for p in sources:shutil.copy2(p,OUT/p.name)
ns='http://www.efinixinc.com/enf_proj';ET.register_namespace('efx',ns)
template=ROOT/'tmp/blue-plate-whole-plate-budget/weight-bank/synthesis/weight_mac8.before.xml'
tree=ET.parse(template);root=tree.getroot();root.set('name','q31_scalar_mac8');root.set('description','Q31 serial requantization sharing frozen partial-sum weight MAC')
design=root.find('{'+ns+'}design_info');design.find('{'+ns+'}top_module').set('name','q31_scalar_mac8')
ET.SubElement(design,'{'+ns+'}design_file',name='psum_scalar_mac8.v',version='default',library='default')
ET.SubElement(design,'{'+ns+'}design_file',name='q31_scalar_mac8.v',version='default',library='default')
root.find('{'+ns+'}constraint_info').find('{'+ns+'}sdc_file').set('name','q31_scalar_mac8.sdc')
tree.write(OUT/'q31_scalar_mac8.xml',encoding='unicode')
(OUT/'q31_scalar_mac8.sdc').write_text('''create_clock -name clk -period 10.000 [get_ports {clk}]
set_input_delay -clock clk -max 0.000 [get_ports {rst ce wr_en wr_addr* wr_data* issue rd_addr* activation* lane_mask* load seed* save restore slot* scalar_read scalar_ready scalar_lane* q_const q_const_value* q_start q_reuse q_acc* q_multiplier* q_shift* q_relu q_zero* q_ready}]
set_input_delay -clock clk -min 0.000 [get_ports {rst ce wr_en wr_addr* wr_data* issue rd_addr* activation* lane_mask* load seed* save restore slot* scalar_read scalar_ready scalar_lane* q_const q_const_value* q_start q_reuse q_acc* q_multiplier* q_shift* q_relu q_zero* q_ready}]
set_output_delay -clock clk -max 0.000 [get_ports {busy done command_error read_valid psum* updated* overflow* scalar_valid scalar_data* q_busy q_valid q_result*}]
set_output_delay -clock clk -min 0.000 [get_ports {busy done command_error read_valid psum* updated* overflow* scalar_valid scalar_data* q_busy q_valid q_result*}]
''')
names=[p.name for p in sources]+['q31_scalar_mac8.xml','q31_scalar_mac8.sdc']
(OUT/'input-hashes.json').write_text(json.dumps({n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in names},indent=2)+'\n')
shutil.copy2(OUT/'q31_scalar_mac8.xml',OUT/'q31_scalar_mac8.before.xml')
print(OUT)
