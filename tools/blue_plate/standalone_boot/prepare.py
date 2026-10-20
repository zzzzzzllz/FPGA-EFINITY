"""Freeze the existing boot sources and prepare an isolated integration patch."""
from pathlib import Path
import difflib
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'coding/edge-quality-30fps'
WORK = ROOT / 'tmp/blue-plate-standalone-boot'
CTRL = 'rtl/cam_i2c_ctrl/i2c/i2c_master_ctrl_top.v'
ROM = 'rtl/cam_i2c_ctrl/i2c/i2c_master_reg_rom.v'
REGSET = 'rtl/cam_i2c_ctrl/i2c/i2c_master_reg_set.v'
TOP = 'rtl/ti60f225_oob_top.v'


def replace(text, old, new, count=1):
    assert text.count(old) == count, (old, text.count(old), count)
    return text.replace(old, new)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    files = [TOP, 'debug_top.v', 'full_view_profile.json',
             *[p.relative_to(SOURCE).as_posix() for p in
               sorted((SOURCE / 'rtl/cam_i2c_ctrl').rglob('*.v'))]]
    before = WORK / 'before'
    manifest = WORK / 'inputs.json'
    if manifest.exists():
        hashes = json.loads(manifest.read_text())
        for name, expected in hashes.items():
            assert hashlib.sha256((before/name).read_bytes()).hexdigest() == expected, name
    else:
        hashes = {}
        for name in files:
            data = (SOURCE/name).read_bytes()
            target = before/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        manifest.write_text(json.dumps(hashes, indent=2) + '\n')
    patch = []
    output_hashes = {}
    for name in hashes:
        target = WORK/'source'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        if name not in [TOP, 'debug_top.v', 'full_view_profile.json', CTRL, ROM, REGSET]:
            target.write_bytes((before/name).read_bytes())
            output_hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
            continue
        original = (before/name).read_text(encoding='utf8')
        text = original
        if name == TOP:
            text = replace(text, 'active_r=397, active_g=256, active_b=471',
                           'active_r=389, active_g=256, active_b=427')
            text = replace(text, 'active_r<=397; active_g<=256; active_b<=471;',
                           'active_r<=389; active_g<=256; active_b<=427;')
            text = replace(text, 'reg [12:0] i2c_rst_cnt', 'reg [15:0] i2c_rst_cnt')
            text = replace(text, 'i2c_rst_cnt[12]', 'i2c_rst_cnt[15]', 2)
            text = replace(text, 'i2c_master_ctrl_top u2_i2c_master_ctrl_top(',
                           'wire sensor_init_success, sensor_init_error;\n'
                           'i2c_master_ctrl_top u2_i2c_master_ctrl_top(\n'
                           '  .init_success(sensor_init_success), .init_error(sensor_init_error),')
        elif name == 'debug_top.v':
            text = replace(text, ".PROBE_OUT0_INIT_VAL    ( 'h18d )", ".PROBE_OUT0_INIT_VAL    ( 'h185 )")
            text = replace(text, ".PROBE_OUT2_INIT_VAL    ( 'h1d7 )", ".PROBE_OUT2_INIT_VAL    ( 'h1ab )")
        elif name == 'full_view_profile.json':
            text = replace(text, '"init": "0x18d"', '"init": "0x185"')
            text = replace(text, '"init": "0x1d7"', '"init": "0x1ab"')
        elif name == CTRL:
            text = replace(text, 'parameter DATA_LENGTH = 164', 'parameter DATA_LENGTH = 166')
            text = replace(text, 'output wire [10:0] sensor_response,',
                           'output wire [10:0] sensor_response,\n'
                           'output wire init_success,\noutput reg init_error,')
            text = replace(text, 'assign sensor_response = {read_byte, configured, error, ack};',
                           'assign sensor_response = {read_byte, configured, error, ack};\n'
                           '// Table completion and successful initialization are distinct states.\n'
                           'assign init_success = configured && !init_error;\n'
                           'always @(posedge clk or negedge rst_n) begin\n'
                           '    if(!rst_n) init_error <= 0;\n'
                           '    else if(!configured && (wr_done || rd_done) && nack_error)\n'
                           '        init_error <= 1;\nend')
        elif name == REGSET:
            text = replace(text, 'parameter DATA_LENGTH = 61', 'parameter DATA_LENGTH = 166')
        elif name == ROM:
            text = replace(text, "{16'h3e01,8'hba,1'b0}", "{16'h3e01,8'h70,1'b0}")
            text = replace(text, "{16'h3e02,8'hd0,1'b0}", "{16'h3e02,8'h80,1'b0}")
            text = replace(text, "{16'h3E09,8'h2a,1'b0}", "{16'h3E09,8'h3f,1'b0}")
            text = replace(text, "ROM[8'ha3] = {16'h0100,8'h01,1'b0};",
                           "ROM[8'ha3] = {16'h3e06,8'h00,1'b0};\n"
                           "ROM[8'ha4] = {16'h3e07,8'h80,1'b0};\n"
                           "ROM[8'ha5] = {16'h0100,8'h01,1'b0};")
        # Preserve the source's line endings so the integration diff stays narrow.
        eol = '\r\n' if b'\r\n' in (before/name).read_bytes() else '\n'
        target.write_bytes(text.replace('\n', eol).encode('utf8'))
        output_hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        patch.extend(difflib.unified_diff(original.splitlines(True), text.splitlines(True),
                     fromfile='a/'+name, tofile='b/'+name))
    (WORK/'standalone-boot.patch').write_text(''.join(patch), encoding='utf8')
    (WORK/'outputs.json').write_text(json.dumps(output_hashes, indent=2)+'\n')
    # The oracle retains all unchanged vendor initialization writes from frozen input.
    # Requested defaults and tail are independently specified here.
    raw = (before/ROM).read_text(encoding='utf8')
    raw = re.sub(r'//[^\n]*|/\*.*?\*/', '', raw, flags=re.S)
    entries = [(int(i,16), int(a,16), int(v,16)) for i,a,v in re.findall(
        r"ROM\[8'h([0-9a-fA-F]+)\]\s*=\s*\{16'h([0-9a-fA-F]+),\s*8'h([0-9a-fA-F]+),1'b0", raw)]
    assert len(entries) == 164 and [x[0] for x in entries] == list(range(164))
    expected = [(a, {0x3e01:0x70,0x3e02:0x80,0x3e09:0x3f}.get(a,v)) for _,a,v in entries[:-1]]
    expected += [(0x3e06,0),(0x3e07,0x80),(0x0100,1)]
    (WORK/'expected.hex').write_text(''.join(f'{a:04x}{v:02x}\n' for a,v in expected))
    top = (WORK/'source'/TOP).read_text(encoding='utf8')
    delay = top[top.index('reg [15:0] i2c_rst_cnt'):top.index('wire sensor_init_success')]
    (WORK/'delay.vh').write_text(delay)
    start = top.index('always @(posedge i_mipi_rx_pclk) begin\n if (!w_arstn) begin\n  active_r')
    end = top.index('raw_full_view full_view(', start)
    (WORK/'gain_active.vh').write_text(top[start:end])
    initial = top[top.index('reg [15:0] active_r='):top.index('wire median_set,denoise_set;')]
    (WORK/'gain_initial.vh').write_text(initial)
    print(f'Prepared {len(hashes)} frozen source files, six-file integration patch: {WORK}')


if __name__ == '__main__':
    main()
