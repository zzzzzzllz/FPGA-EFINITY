"""Reproduce the controller's independent geometry/real-reader lifecycle test.

The testbenches retain the reviewed 2026-10-18 lifecycle checks from
tmp/blue-plate-review/{quad,roi}-lifecycle/tb.sv, with the optional color ports
explicitly disconnected. No external vector files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--roi', action='store_true', help='Start with matrix coefficients instead of corners')
    args = parser.parse_args()
    mode = 'roi' if args.roi else 'quad'
    out = ROOT/'tmp/blue-plate-geometry'/f'{mode}-lifecycle'
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT/'tools/blue_plate/frame_reader/rtl/frame_reader.v']
    modules = ['perspective_coords', 'perspective_fetch', 'perspective_roi']
    if not args.roi:
        modules += ['perspective_matrix', 'perspective_quad']
    sources += [HERE.parent/'rtl'/f'{name}.v' for name in modules]
    sources += [ROOT/'tools/blue_plate/otsu/rtl'/f'{name}.v' for name in ['otsu32', 'roi_otsu32']]
    sources.append(HERE/f'tb_{mode}_lifecycle.sv')
    bin_dir = ROOT/'tools/iverilog-12/app/bin'
    commands = [[str(bin_dir/'iverilog.exe'), '-g2012', '-Wall', '-s', 'tb', '-o', str(out/'sim.vvp'),
                 *map(str, sources)], [str(bin_dir/'vvp.exe'), str(out/'sim.vvp')]]
    source_hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sources}
    logs = []
    for command in commands:
        result = subprocess.run(command, cwd=out, text=True, capture_output=True)
        logs.append(result.stdout+result.stderr)
        (out/'simulation.log').write_text('\n'.join(logs), encoding='utf8')
        if result.returncode:
            raise RuntimeError(logs[-1])
    if 'PASS' not in logs[-1]:
        raise AssertionError('Simulation exited without its final assertions')
    report = dict(pass_=True, mode=mode, source_hashes=source_hashes, commands=commands,
                  log_sha256=hashlib.sha256((out/'simulation.log').read_bytes()).hexdigest())
    (out/'simulation.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(logs[-1])


if __name__ == '__main__':
    main()
