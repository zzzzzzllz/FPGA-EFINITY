"""Offline regression of the frozen standalone boot patch; no board access."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import time
import prepare

ROOT, WORK = prepare.ROOT, prepare.WORK
HERE = Path(__file__).resolve().parent


def main():
    prepare.main()
    sim = ROOT/'tools/iverilog-12/app/bin'
    tests = WORK/'tests'
    tests.mkdir(exist_ok=True)
    for name in ('tb_boot.sv', 'tb_gains.sv'):
        shutil.copy2(HERE/name, tests/name)
    source = WORK/'source'
    base = source/'rtl/cam_i2c_ctrl'
    files = [base/'i2c'/n for n in ('i2c_master_ctrl_top.v', 'i2c_master_reg_set.v',
             'i2c_master_reg_rom.v', 'i2c_16addr_8data.v')]
    files += [base/'i2c_master'/n for n in ('i2c_master_top.v', 'i2c_master_byte_ctrl.v',
              'i2c_master_bit_ctrl.v')]
    gbuf = Path('D:/Efinity/sim_models/verilog/efx_gbufce.v')
    frozen = [*source.rglob('*.v'), source/'full_view_profile.json', *tests.glob('*.sv'),
              *WORK.glob('*.vh'), WORK/'expected.hex', gbuf]
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = {'input_sha256': {str(p):digest(p) for p in frozen}, 'stages':{}}
    report_path = WORK/'execution.json'

    def stage(name, command):
        log = tests/(name+'.log')
        started = time.monotonic()
        with log.open('w') as stream:
            result = subprocess.run([str(x) for x in command], cwd=WORK,
                                    stdout=stream, stderr=subprocess.STDOUT)
        report['stages'][name] = {'command':list(map(str,command)), 'exit_code':result.returncode,
                                'seconds':round(time.monotonic()-started,3), 'log_sha256':digest(log)}
        report_path.write_text(json.dumps(report,indent=2)+'\n')
        print(name, result.returncode, log.read_text(errors='replace')[-3000:], flush=True)
        if result.returncode:
            raise RuntimeError(f'{name} failed: {log}')

    common = [sim/'iverilog.exe','-g2012','-I',WORK,'-I',base/'i2c_master','-s','tb_boot']
    fast = tests/'boot-fast.vvp'
    full = tests/'boot-default.vvp'
    gain = tests/'gains.vvp'
    stage('compile-fast', [*common,'-DFAST','-o',fast,*files,tests/'tb_boot.sv'])
    for mode in range(7):
        stage(f'boot-{mode}', [sim/'vvp.exe',fast,f'+MODE={mode}'])
    stage('compile-gains', [sim/'iverilog.exe','-g2012','-I',WORK,'-s','tb_gains','-o',gain,
                          source/'debug_top.v',gbuf,tests/'tb_gains.sv'])
    stage('gains', [sim/'vvp.exe',gain])
    stage('compile-default', [*common,'-o',full,*files,tests/'tb_boot.sv'])
    stage('boot-default', [sim/'vvp.exe',full,'+MODE=0'])
    for name, value in report['input_sha256'].items():
        assert digest(Path(name)) == value, f'Compiled input changed: {name}'
    originals = json.loads((WORK/'inputs.json').read_text())
    for name,value in originals.items():
        assert digest(prepare.SOURCE/name) == value, f'Shared source changed: {name}'
    profile = json.loads((source/'full_view_profile.json').read_text())
    probes = {p['name']:p['init'] for c in profile['debug_cores'] if c['name']=='status' for p in c['probes']}
    assert [int(probes[n],16) for n in ('r_gain','g_gain','b_gain')] == [389,256,427]
    report['compiled_inputs_unchanged'] = True
    report['shared_sources_unchanged'] = True
    report['profile_defaults_match'] = True
    report['binary_sha256'] = {p.name:digest(p) for p in tests.glob('*.vvp')}
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    shutil.copy2(WORK/'standalone-boot.patch',HERE/'standalone-boot.patch')
    shutil.copy2(WORK/'inputs.json',HERE/'frozen-inputs.json')
    print('PASS all boot regressions; shared sources unchanged',flush=True)


if __name__ == '__main__':
    main()
