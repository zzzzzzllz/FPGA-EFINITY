"""Check exact ROM-content alternatives without modifying fonts, RTL or builds."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / 'docs/validation/blue-plate/whole-plate-budget'
OUT = ROOT / 'tmp/blue-plate-whole-plate-budget/same-firmware'


def main():
    paths = [ROOT / 'tools/blue_plate/plate_display' / p for p in
             ('plate_osd.v', 'plate_font.mem', 'assets.json', 'plate_defs.vh')]
    paths.append(ROOT / 'coding/edge-quality-30fps/rtl/threshold_osd.v')
    paths.append(ROOT / 'docs/validation/blue-plate/plate-display/plate_osd.map.rpt')
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assets = json.loads(paths[2].read_text(encoding='utf-8'))
    font = [int(s, 16) for s in paths[1].read_text().split()]
    section = paths[-1].read_text().split('Resource Summary (begin)', 1)[1].split('Resource Summary (end)', 1)[0]
    mapped = {k: int(v) for k,v in re.findall(r'^(EFX_\w+)\s*:\s*(\d+)', section, re.M)}
    assert len(font) == 4096 and assets['glyph_count'] == 69
    assert hashlib.sha256(paths[1].read_bytes()).hexdigest() == assets['rom_sha256']
    visible = font[:69*32]
    assert all(x == 0 for x in font[68*32:])
    low_rows, high_rows = font[:2048], font[2048:2304]
    low_bits = [(row >> (31-column)) & 1 for row in low_rows for column in range(32)]
    high_bits = [(row >> (31-column)) & 1 for row in font[2048:2176] for column in range(32)]
    dictionary = sorted(set(visible))
    lookup = {row: i for i, row in enumerate(dictionary)}
    indices = [lookup[row] for row in visible]
    checked = 0
    for incoming_glyph in range(128):
        glyph = min(incoming_glyph, 68)
        for y in range(32):
            row = font[glyph*32+y]
            split_row = low_rows[glyph*32+y] if glyph < 64 else high_rows[(glyph-64)*32+y]
            assert split_row == row == dictionary[indices[glyph*32+y]]
            for x in range(32):
                if glyph < 64:
                    bit = low_bits[(glyph*32+y)*32+x]
                elif glyph < 68:
                    bit = high_bits[((glyph-64)*32+y)*32+x]
                else:
                    bit = 0
                assert bit == ((row >> (31-x)) & 1)
                checked += 1
    ink = [(i % 32, 31-b) for i, row in enumerate(visible) for b in range(32) if row >> b & 1]
    result = dict(status='Static content/address equivalence only; no candidate RTL, simulation or map',
                  original=dict(words=4096, width=32, mapped_RAM=mapped['EFX_RAM10'], mapped_LUT4=mapped['EFX_LUT4'], mapped_FF=mapped['EFX_FF']),
                  content=dict(glyphs=69, class_glyphs=65, reachable_rows=len(visible), unused_tail_rows=4096-len(visible),
                               zero_reachable_rows=visible.count(0), nonzero_reachable_rows=sum(bool(v) for v in visible),
                               unique_rows=len(dictionary), unique_nonzero_rows=len(dictionary)-1,
                               ink_y=[min(y for y,x in ink), max(y for y,x in ink)],
                               ink_x=[min(x for y,x in ink), max(x for y,x in ink)],
                               most_common_rows=[dict(hex=f'{v:08x}',count=n) for v,n in Counter(visible).most_common(8)]),
                  candidate_row_split=dict(layout=['2048x32', '256x32'], primitive_modes=['8 * 2048x4', '2 * 512x16'],
                                           architectural_RAM_target=10, actual_RAM=None),
                  candidate_bit_split=dict(layout=['65536x1', '4096x1', 'blank constant'],
                                           primitive_modes=['8 * 8192x1', '1 * 8192x1'], architectural_RAM_target=9,
                                           actual_RAM=None, address='low={glyph[5:0],row[4:0],column[4:0]}; high={glyph[1:0],row[4:0],column[4:0]}',
                                           bit_order='column 0 is original row bit 31', target_registered_read_cycles=1),
                  dictionary=dict(index_width=10, index_entries=2208, row_width=32, row_entries=756,
                                  raw_bits=2208*10+756*32, problem='Two synchronous dependent reads add a cycle; LUT lookup cost unknown'),
                  static_pixel_cases=checked, tested_incoming_ids=128,
                  untested='RTL clock/reset/control equivalence, inference mode, RAM count, mux logic and timing',
                  source_sha256=hashes,
                  research=[dict(url='https://www.efinixinc.com/docs/efinity-quantum-ti-primitives-ug-v1.3.pdf',
                                 section='EFX_RAM10 allowed modes: 8192x1, 2048x4, 512x16; architecture targets require map confirmation')])
    result['sources_unchanged'] = all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p,h in hashes.items())
    assert result['sources_unchanged']
    for directory in (DOC, OUT):
        (directory/'font-storage-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
