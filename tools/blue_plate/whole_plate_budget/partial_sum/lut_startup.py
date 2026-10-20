"""Validate a local simulation-only fix for the vendor LUT time-zero event."""
from pathlib import Path
import hashlib,itertools,json,re,subprocess


def prepare(out,models,sim,netlist):
    original=models/'efx_lut4.v'
    data=original.read_bytes()
    old=b'always @(I0_net or I1_net or I2_net or I3_net) begin'
    assert data.count(old)==1
    local=out/'efx_lut4_startup.sv'
    local.write_bytes(data.replace(old,b'always_comb begin'))
    masks=sorted({int(x,16) for x in re.findall(r'\.LUTMASK = 16\'h([0-9a-fA-F]+);',netlist.read_text())}|{0x0777})
    lines=['`timescale 1ns/1ps','module tb_lut; reg [3:0] a=0;']
    for j,m in enumerate(masks):
        lines += [f"wire o{j}; EFX_LUT4 #(.LUTMASK(16'h{m:04x})) u{j}(.I0(a[0]),.I1(a[1]),.I2(a[2]),.I3(a[3]),.O(o{j}));"]
    lines+=['initial begin #1;']
    for j,m in enumerate(masks):
        lines += [f"if(o{j} !== 1'b{m&1}) $fatal(1,\"startup mask={m:04x}\");"]
    for values in itertools.product('01xz',repeat=4):
        bits=''.join(values);possible=[0]
        for v in values:
            possible=[x*2+b for x in possible for b in ([0,1] if v=='x' else [0 if v=='z' else int(v)])]
        lines += [f"a=4'b{bits}; #1;"]
        for j,m in enumerate(masks):
            outputs={m>>x&1 for x in possible};expected=str(next(iter(outputs))) if len(outputs)==1 else 'x'
            lines += [f"if(o{j} !== 1'b{expected}) $fatal(1,\"table mask={m:04x} input={bits}\");"]
    lines += ['$display("PASS LUT startup and four-state truth tables");$finish;end endmodule']
    tb=out/'tb_lut_startup.sv';tb.write_text('\n'.join(lines)+'\n')
    binary=out/'lut-validation.vvp'
    compiled=subprocess.run([str(sim/'iverilog.exe'),'-g2012','-s','tb_lut','-o',str(binary),str(tb),str(local)],capture_output=True,text=True)
    (out/'lut-validation-compile.log').write_text(compiled.stdout+compiled.stderr)
    assert compiled.returncode==0,compiled.stderr
    run=subprocess.run([str(sim/'vvp.exe'),str(binary)],capture_output=True,text=True)
    (out/'lut-validation-run.log').write_text(run.stdout+run.stderr)
    assert run.returncode==0 and 'PASS LUT' in run.stdout,run.stdout+run.stderr
    result=dict(exit_code=0,unique_masks=len(masks),checks=len(masks)*257,
        change='Local simulation copy: explicit input sensitivity replaced with always_comb; startup evaluation included. No RTL/netlist/vendor installation changes.',
        files_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),original,local,tb,netlist]},stdout=run.stdout)
    (out/'lut-startup-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    return local
