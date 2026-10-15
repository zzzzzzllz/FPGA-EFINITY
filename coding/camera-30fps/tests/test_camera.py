"""Full-field pixel ordering, Bayer phases and gaps using the original RTL test."""
from pathlib import Path
import subprocess

project=Path(__file__).resolve().parents[1]
root=project.parents[1]
work=root/'tmp/tests/camera-30fps'
work.mkdir(parents=True,exist_ok=True)
sim=root/'tools/iverilog-12/app/bin'
exe=work/'full-view.vvp'
subprocess.run([str(sim/'iverilog.exe'),'-g2012','-s','tb_full_view','-Ptb_full_view.W=2560','-Ptb_full_view.H=1440','-o',str(exe),str(project/'rtl/raw_full_view.v'),str(project/'tests/tb_full_view.v')],check=True,cwd=project)
subprocess.run([str(sim/'vvp.exe'),str(exe)],check=True,cwd=project)
