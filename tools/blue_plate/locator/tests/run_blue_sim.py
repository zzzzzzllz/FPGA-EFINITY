"""Exhaustive RTL H/S mask comparison with OpenCV; stalls, gate and cancellation."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'tools/blue_plate'))
from blue_mask_integer import blue_tables


def main():
    out = ROOT/'tmp/blue-plate-locator/blue-mask'
    out.mkdir(parents=True, exist_ok=True)
    sat, hue = blue_tables()
    for name, values, bits in [('blue_saturation', sat, 8), ('blue_hue', hue, 9)]:
        mask = (1 << bits)-1
        (out/f'{name}.mem').write_text(''.join(f'{((int(hi)&mask)<<bits)|(int(lo)&mask):x}\n'
                                              for lo, hi in values), encoding='ascii')
    r, g = np.indices((256, 256), dtype=np.uint8)
    image = np.empty((256, 256, 3), np.uint8)
    image[..., 1], image[..., 2] = g, r
    with (out/'expected.mem').open('w', encoding='ascii') as f:
        for b in range(256):
            image[..., 0] = b
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            expected = ((hsv[..., 0] > 100) & (hsv[..., 0] < 140) &
                        (hsv[..., 1] > 95) & (hsv[..., 1] < 255))
            for row in np.packbits(expected, axis=1, bitorder='little'):
                f.write(f'{int.from_bytes(row.tobytes(), "little"):064x}\n')
    sources = [HERE.parent/'rtl/blue_hs_filter.v', HERE/'tb_blue_hs_filter.sv']
    files = sources+[ROOT/'tools/blue_plate/blue_mask_integer.py', out/'blue_saturation.mem',
                     out/'blue_hue.mem', out/'expected.mem']
    hashes = {str(p.relative_to(ROOT)).replace('\\','/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    binaries = ROOT/'tools/iverilog-12/app/bin'
    commands = [[str(binaries/'iverilog.exe'), '-g2012', '-Wall', '-s', 'tb_blue_hs_filter',
                 '-o', str(out/'sim.vvp'), *map(str, sources)], [str(binaries/'vvp.exe'), str(out/'sim.vvp')]]
    logs = []
    for command in commands:
        result = subprocess.run(command, cwd=out, text=True, capture_output=True)
        logs.append(result.stdout+result.stderr)
        (out/'simulation.log').write_text('\n'.join(logs), encoding='utf8')
        if result.returncode:
            raise RuntimeError(logs[-1])
    if 'PASS blue mask' not in logs[-1]:
        raise AssertionError('Missing final assertions')
    report = dict(pass_=True, opencv=cv2.__version__, source_hashes=hashes, commands=commands,
                  log_sha256=hashlib.sha256((out/'simulation.log').read_bytes()).hexdigest())
    (out/'simulation.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(logs[-1])


if __name__ == '__main__':
    main()
