"""Verify the candidate compositor/HDMI timing/metadata path with changing RGB."""
import argparse
import subprocess
from generate import ROOT, SOURCE, WORK, replace_once


def main(full):
    work = WORK / 'live'
    output = WORK / 'tests'
    output.mkdir(exist_ok=True)
    tb = (SOURCE / 'tests/tb_frame_display.v').read_text(encoding='utf-8')
    start = tb.index(' always @(posedge clk) if(rst && de && osd.y>0)')
    end = tb.index(' wire reset_fifo', start)
    tb = tb[:start] + ''' always @(posedge clk) if(rst && de && osd.y>0) begin
  if(shown_flags!==0 || shown_threshold!==0 || shown_descriptor!==expected_descriptor)
   $fatal(1,"live metadata mismatch");
  if(osd_rgb!==video[23:0]) $fatal(1,"RGB changed by metadata receiver");
 end
''' + tb[end:]
    start = tb.index(' wire [15:0] display_config=')
    end = tb.index('\n', start)
    tb = tb[:start] + " wire [15:0] display_config=16'd0;" + tb[end:]
    start = tb.index(' wire [300:0] expected_descriptor=')
    end = tb.index('\n', start)
    tb = tb[:start] + " wire [300:0] expected_descriptor={7'd0,frame_descriptor};" + tb[end:]
    tb = replace_once(tb, "wire [293:0] frame_descriptor=REFERENCE ? (294'd1<<101) : 294'd0;",
                      "wire [293:0] frame_descriptor=294'(tag) | (294'(tag%3)<<96) | (294'(tag*17)<<32);")
    tb = replace_once(tb, "comp(clk,rst,period,1'(!REFERENCE),1'b0,1'b0,(!REFERENCE && tag!=3)",
                      "comp(clk,rst,period,1'b0,1'b0,1'b0,1'b0")
    start = tb.index('  begin pixel=')
    end = tb.index(' endfunction', start)
    tb = tb[:start] + '''  begin
   pixel={1'b0,7'(n),8'(xx*37+yy*13+n*17),8'(xx*11+yy*53+n*29),8'(xx*7+yy*3+n*61)};
   if(yy==0 && (xx==1 || xx==2)) pixel[30:24]=0;
  end
''' + tb[end:]
    start = tb.index('   if(REFERENCE) begin', tb.index(' always @(negedge clk) if(rst)'))
    end = tb.index('   if(y==0 && x>=2 && x<=44)', start)
    tb = tb[:start] + "   p=pixel(tag,x,y);expected={8'd0,p[23:0]};\n" + tb[end:]
    tb = tb.replace('3 full %0dx%0d split frames', '3 full %0dx%0d live RGB frames')
    path = output / 'tb_live_display.v'
    path.write_text(tb, encoding='utf-8')
    name = 'display-full' if full else 'display-short'
    exe = output / (name + '.vvp')
    sim = ROOT / 'tools/iverilog-12/app/bin'
    files = ['frame_store_dma', 'frame_buffer_V4/DC_FIFO', 'user_cvo_axi_v2/cvo_axi_v2', 'compare_display', 'threshold_osd']
    commands = [[sim / 'iverilog.exe', '-g2012', *([] if full else ['-DSHORT_DISPLAY']), '-s', 'tb_frame_display', '-o', exe,
                 *[work / 'rtl' / (f + '.v') for f in files], path], [sim / 'vvp.exe', '-i', exe]]
    for stage, command in zip(('compile', 'run'), commands):
        log = output / (name + '-' + stage + '.log')
        with log.open('w') as stream:
            result = subprocess.run([str(x) for x in command], cwd=work, stdout=stream, stderr=subprocess.STDOUT)
        print(log.read_text()[-1200:], flush=True)
        if result.returncode:
            raise RuntimeError(f'{stage} failed; see {log}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true')
    main(parser.parse_args().full)
