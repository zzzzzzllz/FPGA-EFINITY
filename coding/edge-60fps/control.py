"""Control the independent 720p60 area-filtered camera build."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.extend([os.environ['EFXDBG_HOME']+'/bin', os.environ['EFXPGM_HOME']+'/bin'])
from efx_dbg.define import DebugProfileBuilder
from efx_dbg.jtag import VioController
from efx_pgm.define import JtagParameters
from efx_pgm.efx_hw_manager import EfxHwManager
from efx_pgm.usb_resolver import UsbResolver
from efx_pgm.util.gen_util import set_efinity_user_dir_env
from pyftdi.bits import BitSequence


class Console:
    write = staticmethod(print)
    write_error_msg = staticmethod(print)
    write_warning_msg = staticmethod(print)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--samples', type=int, default=5)
parser.add_argument('--interval', type=float, default=1)
parser.add_argument('--edge', action='store_true', default=True, help='Use the edge-system project')
parser.add_argument('--view', choices=('color', 'gray', 'edge'), help='Edge display mode; keeps active gains')
parser.add_argument('--set', nargs=5, type=lambda s: int(s, 0),
                    metavar=('R', 'G', 'B', 'GAMMA', 'PHASE'),
                    help='Q8.8 gains (256=1x), gamma 0/1, Bayer phase 0..3')
args = parser.parse_args()
if args.view and not args.edge:
    parser.error('--view requires --edge')
if args.samples < 1 or args.interval < 0:
    parser.error('Sample count must be positive; interval cannot be negative')
if args.set and (any(not 1 <= x <= 4096 for x in args.set[:3]) or
                 args.set[3] not in (0, 1) or args.set[4] not in range(4)):
    parser.error('Gains must be 1..4096, gamma 0/1, phase 0..3')
root = Path(__file__).resolve().parent
project = root
profile, warning = DebugProfileBuilder.from_file(str(
    root/'full_view_profile.json'))
if warning:
    raise ValueError(warning)
set_efinity_user_dir_env()
targets = UsbResolver().get_usb_connections()
if len(targets) != 1:
    raise RuntimeError(f'Expected one FPGA programmer, found {len(targets)}')
manager = EfxHwManager(Console())
params = JtagParameters(frequency=1e6, url=targets[0].URLS[1], target_num=1,
    devices=[{'chip_num': 1, 'id_code': '0x10660A79', 'ir_width': 5, 'istr_code': '11000'}],
    jtag_user='USER1', jtag_backend='pyftdi', plain_jtag=False)
session = manager.create_jtag_session(params)
try:
    # Efinity's VIO constructor otherwise resets live controls on every read.
    # Keep protocol initialization and UUID checks, but preserve probe outputs.
    with patch.object(VioController, 'soft_reset_probe_out', return_value=None):
        debug = manager.create_debug_session(session, profile)
    try:
        probes = list(profile.get_core_spec('status').get_probe_ins())

        def read():
            data = manager.vio_read(debug, 'status')
            values = {name: int(value) for (name, _), value in zip(probes, data, strict=True)}
            expected_id = 0x60101065 if args.edge else 0x60101001
            if values['build_id'] != expected_id:
                raise RuntimeError(f'Expected build {expected_id:#x}, got {values["build_id"]:#x}')
            if values['sensor_exposure_gain'] != 0x0565803d:
                raise RuntimeError(f"Exposure/gain readback mismatch: {values['sensor_exposure_gain']:#010x}")
            return values

        current = read()
        if args.set or args.view:
            settings = args.set
            widths = [16, 16, 16, 1, 2]
            if args.edge:
                if settings is None:
                    settings = [current[name] for name in
                                ('active_r', 'active_g', 'active_b', 'active_gamma', 'active_phase')]
                view = int(args.view == 'gray') if args.view else current['active_gray']
                edge = int(args.view == 'edge') if args.view else current['active_edge']
                settings = [*settings, view, edge]
                widths.extend([1, 1])
            manager.vio_write(debug, 'status', [BitSequence(v, length=w)
                for v, w in zip(settings, widths, strict=True)])
            print(json.dumps({'set': settings}), flush=True)
            time.sleep(0.3)
        start = time.monotonic()
        for i in range(args.samples):
            print(json.dumps({'elapsed_s': round(time.monotonic()-start, 3),
                              'signals': read()}), flush=True)
            if i+1 < args.samples:
                time.sleep(args.interval)
    finally:
        manager.close_debug_session(debug)
finally:
    manager.close_jtag_session(session)

