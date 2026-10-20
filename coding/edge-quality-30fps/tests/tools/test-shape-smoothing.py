"""Check recognition smoothing against RTL and compare stationary noisy contours."""
import json
import subprocess
from pathlib import Path

import numpy as np
from canny_reference import classify, hysteresis, vectors, windows

project = Path(__file__).resolve().parents[2]
repo = project.parents[1]
work = repo / 'tmp/tests' / project.name / 'shape-smoothing'
work.mkdir(parents=True, exist_ok=True)
sim = repo / 'tools/iverilog-12/app/bin'
exe = work / 'local.vvp'
subprocess.run([str(sim/'iverilog.exe'), '-g2012', '-s', 'tb_canny_local', '-o', str(exe),
                *[str(project/'rtl'/f'{n}.v') for n in
                  ('median_pair', 'gaussian_pair', 'sobel_pair', 'canny_nms_pair', 'edge_algorithm_pair')],
                str(project/'tests/tb_canny_local.v')], check=True)
vectors(work, 32, 24, recognition=True)
for case in json.loads((work/'manifest.json').read_text()):
    subprocess.run([str(sim/'vvp.exe'), str(exe), '+recognition=1', '+jobs=3', f'+config={case["config"]}',
                    f'+input={work/case["name"]}-input.hex',
                    f'+expected={work/case["name"]}-class.hex'], check=True)

# Identical stationary targets and noise samples for both filters. The one-pixel
# coverage metric tolerates edge location quantization, but off-contour noise does not.
rng = np.random.default_rng(817)
y, x = np.indices((192, 192))
results = []
for name, mask in [('circle', (x-96)**2+(y-96)**2 < 48**2),
                   ('rectangle', (x>42)&(x<150)&(y>50)&(y<140))]:
    clean = np.where(mask, 65, 175).astype(np.uint8)
    target = hysteresis(classify(clean, 56)[0])[0]
    near = np.maximum.reduce(windows(target)) > 0
    far = ~(np.maximum.reduce(windows(near)) > 0)
    frames = [np.clip(clean.astype(float)+rng.normal(0, 12, clean.shape), 0, 255).astype(np.uint8)
              for _ in range(16)]
    pair = []
    for enhanced in (False, True):
        edges = [hysteresis(classify(a, 56, recognition=enhanced)[0])[0] for a in frames]
        row = dict(shape=name, enhanced=enhanced,
                   changed_pixels=float(np.mean([np.count_nonzero(a!=b) for a,b in zip(edges, edges[1:])])),
                   off_contour_pixels=float(np.mean([np.count_nonzero(a&far) for a in edges])),
                   coverage=float(np.mean([np.mean(np.maximum.reduce(windows(a))[target]>0) for a in edges])))
        pair.append(row)
        results.append(row)
    assert pair[1]['changed_pixels'] < pair[0]['changed_pixels'] * 0.5, pair
    assert pair[1]['off_contour_pixels'] < pair[0]['off_contour_pixels'] * 0.5, pair
    assert pair[1]['coverage'] >= 0.99, pair
(work/'comparison.json').write_text(json.dumps(results, indent=2)+'\n')
print(json.dumps(results, indent=2))
print('PASS recognition smoothing: 96 RTL frames, stalls/changing frame tags/RGB, 32-frame noise comparison')
