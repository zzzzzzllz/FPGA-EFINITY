"""A failed AXI response or unsupported byte mask must prevent publication."""
from pathlib import Path
work=Path(__file__).resolve().parents[4]/'tmp/tests'/Path(__file__).resolve().parents[2].name
work.mkdir(parents=True,exist_ok=True)
import subprocess

root = Path(__file__).resolve().parents[1]
project=root.parent
sim=Path(__file__).resolve().parents[4]/'tools/iverilog-12/app/bin'
exe = work / 'm09-fault.vvp'
subprocess.run([str(sim/'iverilog.exe'), '-g2012', '-s', 'tb_canny_hysteresis', '-o', str(exe),
                str(project/'rtl/canny_hysteresis.v'), str(project/'tests'/'tb_canny_hysteresis.v')], check=True)
for arg in [f'+error_at={n}' for n in (1, 2, 3, 5, 10, 15, 20)]:
    subprocess.run([str(sim/'vvp.exe'), str(exe), '+config=26656',
                    f'+input={work}/m09-vectors/weak-dense-class.hex',
                    f'+expected={work}/m09-vectors/weak-dense-final.hex', arg], check=True)
print('PASS 7 DDR failure cases')
