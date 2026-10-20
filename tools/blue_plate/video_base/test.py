"""Reuse the existing AXI/CDC scoreboard with the candidate RGB passthrough."""
import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from generate import ROOT, SOURCE, WORK, replace_once


def main(full):
    work = WORK / 'live'
    output = WORK / 'tests'
    output.mkdir(exist_ok=True)
    tb = (SOURCE / 'tests/tb_frame_store.v').read_text(encoding='utf-8')
    tb = replace_once(tb, "config_value=13'd2080", "config_value=16'd0")
    tb = replace_once(tb, ' reg [31:0] last_shown_id=0,last_shown_epoch=0;',
                      ' reg [31:0] last_shown_id=0,last_shown_epoch=0;\n reg [31:0] completed_frame_id=0,completed_frame_epoch=0;\n reg [3:0] completed_ids=0;\n integer verified_words[0:3];')
    tb = replace_once(tb, '   if(shown_words==WORDS) shown_frames=shown_frames+1;', '''   if(shown_words==WORDS) begin
    shown_frames=shown_frames+1;
    completed_frame_id=desc[31:0];completed_frame_epoch=desc[63:32];
    if(desc[31:0]>=10 && desc[31:0]<=13 && desc[63:32]==0) begin
     completed_ids[desc[31:0]-10]=1;verified_words[desc[31:0]-10]=shown_words;
    end
   end''')
    start = tb.index(' wire edge0=')
    end = tb.index(' function integer gray(', start)
    tb = tb[:start] + ''' video_rgb_passthrough pass_rgb(
 .clk(pixel_clk),.rst_n(rst_n),.in_config(algorithm_config),.in_recognition(1'b0),
 .in_pixels(algorithm_pixels),.in_valid(algorithm_valid),.in_ready(algorithm_ready),
 .in_sof(algorithm_sof),.in_eol(algorithm_eol),.in_eof(algorithm_eof),.in_id(algorithm_frame_id),.in_epoch(algorithm_epoch),
 .out_pixels(result_pixels),.out_valid(result_valid),.out_ready(result_ready),
 .out_sof(result_sof),.out_eol(),.out_eof(result_eof),.out_id(),.out_epoch(),.out_config());
''' + tb[end:]
    start = tb.index('`ifdef REAL_ALGORITHM')
    end = tb.index('    if(desc[101])', start)
    tb = tb[:start] + "    edge_expected=1'b0;\n" + tb[end:]
    # Full-size testing also uses distinct RGB channels and changing per-pixel data.
    start = tb.index('`ifdef FULL_SMOKE', tb.index(' function [31:0] pixel'))
    end = tb.index('   y=77*r', start)
    tb = tb[:start] + '   r=frame+index*7;g=frame*3+index*11;b=frame*13+index*5;\n' + tb[end:]
    start = tb.index(' integer n,prior;')
    end = tb.index(' initial begin #(W==1280', start)
    tb = tb[:start] + ''' integer n,prior;
 always @(negedge display_clk) display_ready=cycles%11!=0;
 initial begin
  for(n=0;n<4;n=n+1) verified_words[n]=0;
  repeat(20) @(negedge pixel_clk);rst_n=1;#1000;
  for(n=10;n<14;n=n+1) begin
   capture(n);await_frame(n,0);
   wait(completed_frame_id==n && completed_frame_epoch==0);
   $display("CHECK changing RGB frame %0d complete words=%0d expected=%0d",n,verified_words[n-10],WORDS);
  end
  if(completed_ids!==4'b1111) $fatal(1,"missing distinct completed frame IDs");
  for(n=0;n<4;n=n+1) if(verified_words[n]!=WORDS) $fatal(1,"incomplete frame %0d",n+10);
  if(capture_overflow || result_overflow || status[319:256]!=0 || status[18:0]!=0)
   $fatal(1,"FIFO/bus/frame/history error %h",status);
  $display("PASS live RGB %0dx%0d: four changing frames, exact RGB/coordinates, AXI and display stalls, no history commands",W,H);
  $finish;
 end
''' + tb[end:]
    path = output / 'tb_live_rgb.v'
    path.write_text(tb, encoding='utf-8')
    sim = ROOT / 'tools/iverilog-12/app/bin'
    files = ['frame_store', 'frame_store_control', 'frame_store_dma', 'frame_pair_fifo', 'frame_mailbox',
             'frame_buffer_V4/DC_FIFO', 'video_rgb_passthrough']
    name = 'full-complete' if full else 'small-complete'
    snapshot=output/(name+'-inputs')
    snapshot.mkdir(exist_ok=True)
    shutil.copy2(path,snapshot/path.name)
    for f in files:
        destination=snapshot/'rtl'/(f+'.v');destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(work/'rtl'/(f+'.v'),destination)
    exe = output / (name + '.vvp')
    commands = [[sim / 'iverilog.exe', '-g2012', *(['-DFULL_SMOKE'] if full else []), '-s', 'tb_frame_store', '-o', exe,
                 *[snapshot / 'rtl' / (f + '.v') for f in files], snapshot/path.name], [sim / 'vvp.exe', '-i', exe]]
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    report={'input_sha256':{p.relative_to(snapshot).as_posix():digest(p) for p in snapshot.rglob('*') if p.is_file()},
            'commands':[[str(x) for x in command] for command in commands],'stages':{}}
    report_path=output/(name+'-execution.json')
    report_path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    for stage, command in zip(('compile', 'run'), commands):
        log = output / (name + '-' + stage + '.log')
        start=time.monotonic()
        with log.open('w') as stream:
            result = subprocess.run([str(x) for x in command], cwd=work, stdout=stream, stderr=subprocess.STDOUT)
        report['stages'][stage]={'exit_code':result.returncode,'seconds':round(time.monotonic()-start,3),'log_sha256':digest(log)}
        if exe.exists():report['vvp_sha256']=digest(exe)
        report_path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
        print(log.read_text()[-2500:], flush=True)
        if result.returncode:
            raise RuntimeError(f'{stage} failed; see {log}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true')
    main(parser.parse_args().full)
