"""Prepare isolated Efinity map projects; never call the shared build flow."""
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
for top in ['plate_osd','plate_display']:
    out=ROOT/'tmp/blue-plate-plate-display/synthesis'/top;out.mkdir(parents=True,exist_ok=True)
    sources=['plate_osd.v'] if top=='plate_osd' else ['plate_confirm.v','plate_mailbox.v','plate_display_state.v','plate_osd.v','plate_display.v']
    for name in sources+['plate_defs.vh','plate_font.mem']:
        shutil.copy2(HERE/name,out/name)
    # Local project uses a local ROM path; hardware logic is unchanged.
    for name in sources:
        p=out/name;p.write_text(p.read_text().replace('tools/blue_plate/plate_display/plate_font.mem','plate_font.mem'),encoding='ascii')
    sdc='create_clock -name clk -period 13.468 [get_ports {clk}]\n' if top=='plate_osd' else 'create_clock -name src_clk -period 10.000 [get_ports {src_clk}]\ncreate_clock -name pixel_clk -period 13.468 [get_ports {pixel_clk}]\n'
    (out/(top+'.sdc')).write_text(sdc,encoding='ascii')
    files=''.join(f'<efx:design_file name="{name}" version="default" library="default"/>' for name in sources)
    xml=f'''<efx:project xmlns:efx="http://www.efinixinc.com/enf_proj" name="{top}" description="Independent plate display map only" sw_version="2026.1.132.4.5">
<efx:device_info><efx:family name="Titanium"/><efx:device name="Ti60F225"/><efx:timing_model name="I3"/></efx:device_info>
<efx:design_info def_veri_version="sv_09" def_vhdl_version="vhdl_2008" unified_flow="false"><efx:top_module name="{top}"/>{files}</efx:design_info>
<efx:constraint_info><efx:sdc_file name="{top}.sdc"/><efx:inter_file name=""/></efx:constraint_info>
<efx:sim_info/><efx:misc_info/><efx:ooc_info/><efx:ip_info/>
<efx:synthesis tool_name="efx_map"><efx:param name="work_dir" value="work_syn" value_type="e_string"/>
<efx:param name="max_threads" value="2" value_type="e_integer"/><efx:param name="use-logic-for-small-rom" value="0" value_type="e_integer"/>
<efx:param name="mult-auto-pipeline" value="0" value_type="e_option"/><efx:param name="retiming" value="0" value_type="e_option"/>
</efx:synthesis></efx:project>'''
    (out/(top+'.xml')).write_text(xml,encoding='utf8')
    (out/'source-hashes.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.suffix in ['.v','.vh','.mem','.xml','.sdc']},indent=2),encoding='utf8')
    print(out)
