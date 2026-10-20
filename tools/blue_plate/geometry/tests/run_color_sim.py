"""Check the RGB export against frozen development ROIs and real reader lifecycle."""
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
from geometry_sampler import sample_integer
from run_fetch_sim import threshold


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out = ROOT/'tmp/blue-plate-geometry/color-output'
    out.mkdir(parents=True, exist_ok=True)
    fixture = ROOT/'tmp/blue-plate-char-segment/experiment'
    manifest_path = fixture/'dev-manifest.json'
    inputs_path = fixture/'dev-inputs.npz'
    records = json.loads(manifest_path.read_text(encoding='utf8'))['records']
    assert all(r['original_split'] == 'development' for r in records)
    # Selection uses source hashes, never OCR labels, scores or calibration images.
    selected = sorted(records, key=lambda r: (r['source_sha256'], r['roi_index']))[:4]
    frozen = np.load(inputs_path)['bgr']
    modules = ['perspective_coords', 'perspective_fetch', 'perspective_roi',
               'perspective_matrix', 'perspective_quad']
    sources = [ROOT/'tools/blue_plate/frame_reader/rtl/frame_reader.v']
    sources += [HERE.parent/'rtl'/f'{n}.v' for n in modules]
    sources += [ROOT/'tools/blue_plate/otsu/rtl'/f'{n}.v' for n in ['otsu32', 'roi_otsu32']]
    bench = HERE/'tb_quad_color.sv'
    sources.append(bench)
    bins = ROOT/'tools/iverilog-12/app/bin'
    commands = []

    def run(command, cwd):
        result = subprocess.run(list(map(str, command)), cwd=cwd, text=True, capture_output=True)
        commands.append(dict(command=list(map(str, command)), cwd=str(cwd),
                             returncode=result.returncode, output=result.stdout+result.stderr))
        (out/'commands.json').write_text(json.dumps(commands, indent=2), encoding='utf8')
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)
        return result.stdout

    executables = {}
    for mode, real, enabled in [('color', 1, 1), ('disabled', 1, 0), ('lifecycle', 0, 1)]:
        executable = out/f'{mode}.vvp'
        run([bins/'iverilog.exe', '-g2012', '-Wall', '-s', 'tb',
             f'-Ptb.REAL_FRAME={real}', f'-Ptb.COLOR_ENABLE={enabled}',
             '-o', executable, *sources], out)
        executables[mode] = executable
    results = []
    for record in selected:
        case = out/f"dev-{record['sample_index']}-roi-{record['roi_index']}"
        case.mkdir(exist_ok=True)
        source = ROOT/record['path']
        assert sha(source) == record['source_sha256']
        image = cv2.imdecode(np.frombuffer(source.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        h, w = image.shape[:2]
        scale = min(1280/w, 720/h)
        nw, nh = round(w*scale), round(h*scale)
        dx, dy = (1280-nw)//2, (720-nh)//2
        frame = np.zeros((720, 1280, 3), np.uint8)
        frame[dy:dy+nh, dx:dx+nw] = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)
        sampled, _ = sample_integer(frame, record['points'], 32, integer_solver=True)
        expected = frozen[record['roi_index']]
        assert hashlib.sha256(expected.tobytes()).hexdigest() == record['roi_bgr_sha256']
        assert np.array_equal(sampled, expected)
        assert np.any(expected[:, :, 0] != expected[:, :, 2]), 'Fixture must detect swapped channels'
        rgb = expected[:, :, ::-1].copy()
        raw = frame[:, :, ::-1].copy().tobytes()
        (case/'frame.mem').write_text(''.join(raw[i:i+16].hex()+'\n' for i in range(0, len(raw), 16)))
        (case/'pixels.mem').write_text(''.join(bytes(p).hex()+'\n' for p in rgb.reshape(-1, 3)))
        (case/'corners.mem').write_text(''.join(f'{round(v*65536)&0xffffffff:08x}\n'
                                               for point in record['points'] for v in point))
        # Cast every channel before multiplication, matching the original gray contract.
        gray = ((rgb.astype(np.uint32)*np.array([77, 150, 29], np.uint32)).sum(2) >> 8)
        th = threshold(np.bincount((gray >> 3).ravel(), minlength=32).tolist())
        (case/'threshold.mem').write_text(f'{th:02x}\n')
        for mode in ['color', 'disabled']:
            log = run([bins/'vvp.exe', executables[mode]], case)
            assert 'PASS' in log
            (case/f'{mode}.log').write_text(log)
            print(f"sample {record['sample_index']} {mode}: {log.strip()}", flush=True)
        results.append(dict(sample_index=record['sample_index'], roi_index=record['roi_index'],
                            source_sha256=record['source_sha256'], roi_bgr_sha256=record['roi_bgr_sha256'],
                            pixels=14336, threshold=th))
    log = run([bins/'vvp.exe', executables['lifecycle']], out)
    assert 'PASS COLOR QUAD lifecycle' in log
    (out/'lifecycle.log').write_text(log)
    print(log, flush=True)
    report = dict(pass_=True, selection='first four development ROI records sorted by source SHA256 and ROI index',
                  real_cases=results, pixels_per_mode=4*14336, heldout_consumed=0, calibration_consumed=0,
                  source_hashes={str(p.relative_to(ROOT)): sha(p) for p in [*sources, Path(__file__),
                                 ROOT/'tools/blue_plate/geometry_sampler.py', manifest_path, inputs_path]})
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
