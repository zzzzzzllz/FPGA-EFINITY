"""Read the full-field camera and set its Bayer phase or white balance."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.paged_status import read_snapshot
from tools import sensor_control

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
parser.add_argument('--threshold', type=int, help='Threshold: Sobel 0..2040, Canny 1..2040')
parser.add_argument('--view', choices=('color', 'gray', 'edge', 'compare', 'denoise', 'overlay', 'reference'), help='Edge display mode; keeps active gains')
parser.add_argument('--frame', choices=('live','freeze','step','record','play','pause','next','reference','clear-reference'), help='Frame operation; record explicitly replaces the 32-frame clip')
parser.add_argument('--set', nargs=5, type=lambda s: int(s, 0),
                    metavar=('R', 'G', 'B', 'GAMMA', 'PHASE'),
                    help='Q8.8 gains (256=1x), gamma 0/1, Bayer phase 0..3')
parser.add_argument('--algorithm', choices=('sobel','canny'), help='Frame-committed edge algorithm')
parser.add_argument('--low-ratio', choices=('1/4','1/2','3/4'), help='Canny low/high threshold ratio')
parser.add_argument('--median', choices=('on','off'), help='Frame-committed median filter')
parser.add_argument('--recognition', choices=('on','off'), help='Frame-committed circle/rectangle recognition')
parser.add_argument('--sensor-status', action='store_true', help='Read O1 sensor timing, exposure and gain')
exposure_args = parser.add_mutually_exclusive_group()
exposure_args.add_argument('--exposure-half-lines', type=int, help='SC431HAI manual exposure in half-lines')
exposure_args.add_argument('--exposure-ms', type=float, help='Exposure in ms, calibrated from measured capture FPS')
parser.add_argument('--sensor-gain', choices=('1','2','3'), help='Analog gain 1x, 2.021x or 3.032x; digital gain stays 1x')
parser.add_argument('--sensor-save', type=Path, help='Save sensor registers to a new JSON file')
parser.add_argument('--sensor-restore', type=Path, help='Restore exposure/gain from a saved O1 JSON file')
args = parser.parse_args()
sensor_change = args.exposure_half_lines is not None or args.exposure_ms is not None or args.sensor_gain is not None or args.sensor_restore is not None
sensor_request = sensor_change or args.sensor_status or args.sensor_save is not None
if sensor_request and not args.edge:
    parser.error('Sensor control requires --edge and the O1 bitstream/profile')
if sensor_request and (args.set or args.view or args.frame or args.algorithm or args.low_ratio or args.median or args.recognition or args.threshold is not None):
    parser.error('Apply sensor and display/algorithm controls in separate commands')
if args.sensor_restore and (args.exposure_ms is not None or args.exposure_half_lines is not None or args.sensor_gain is not None):
    parser.error('--sensor-restore cannot be combined with exposure/gain changes')
if (args.algorithm or args.low_ratio) and not args.edge: parser.error('--algorithm/--low-ratio requires --edge')
if args.median and not args.edge: parser.error('--median requires --edge')
if args.recognition and not args.edge: parser.error('--recognition requires --edge')
if args.frame and not args.edge: parser.error('--frame requires --edge')
if args.threshold is not None and (not args.edge or not 0 <= args.threshold <= 2040):
    parser.error("--threshold requires --edge and a value in 0..2040")
if args.view and not args.edge:
    parser.error('--view requires --edge')
if args.samples < 1 or args.interval < 0:
    parser.error('Sample count must be positive; interval cannot be negative')
if args.set and (any(not 1 <= x <= 4096 for x in args.set[:3]) or
                 args.set[3] not in (0, 1) or args.set[4] not in range(4)):
    parser.error('Gains must be 1..4096, gamma 0/1, phase 0..3')
root = Path(__file__).resolve().parent
if not args.edge: parser.error('This control belongs to the quality_preserve edge build; use --edge')
project = root
profile, warning = DebugProfileBuilder.from_file(str(
    project/'full_view_profile.json'))
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
        if args.edge:
            snapshot_layout = json.loads((project/'status_snapshot.json').read_text())

        def read():
            if args.edge:
                values = read_snapshot(manager, debug, snapshot_layout, BitSequence)
            else:
                data = manager.vio_read(debug, 'status')
                values = {name: int(value) for (name, _), value in zip(probes, data, strict=True)}
            expected_id = 0x6010100f
            if values['build_id'] != expected_id:
                raise RuntimeError(f'Expected build {expected_id:#x}, got {values["build_id"]:#x}')
            if args.edge:
                state, ui = values['frame_state'], values['ui_state']
                values.update(frame_mode=state & 7, recorded_frames=(state >> 3) & 63,
                              playback_index=(state >> 9) & 31, reference_valid=(state >> 14) & 1,
                              frame_command_error=(state >> 15) & 15,
                              ui_focus=ui & 7, ui_action=(ui >> 3) & 15, ui_view=(ui >> 7) & 7,
                              ui_median=(ui >> 10) & 1, ui_busy=(ui >> 11) & 1,
                              ui_error=(ui >> 12) & 7, ui_apply_ack=(ui >> 15) & 1,
                              algorithm=(ui >> 16) & 1, low_ratio=(ui >> 17) & 3,
                              algorithm_shown=(ui >> 19) & 1, low_ratio_shown=(ui >> 20) & 3,
                              applying=(ui >> 22) & 1, recognition=(ui >> 23) & 1)
                shapes=values['memory_traffic'] >> 288
                values.update(recognition_shown=(shapes >> 188)&1,shape_overflow=(shapes >> 187)&1,shape_count=(shapes >> 184)&7)
                values['shapes']=[dict(kind=(shapes >> (176+2*i))&3,
                    box=[(shapes >> (44*i+11*j))&2047 for j in range(4)]) for i in range(values['shape_count'])]
                for i,name in enumerate(('processing_cycles','queue_enqueued','queue_highwater','cache_misses')):
                    values[name]=(values['memory_traffic'] >> (160+32*i)) & 0xffffffff
                for i, name in enumerate(('capture_write_beats','result_write_beats','algorithm_read_beats','display_read_beats','reference_read_beats')):
                    values[name] = (values['memory_traffic'] >> (32*i)) & 0xffffffff
            return values

        current = read()
        if sensor_request:
            sensor = sensor_control.Sensor(manager, debug, BitSequence)
            before = sensor_control.inspect(sensor)
            if args.sensor_save:
                sensor_control.save(args.sensor_save, before)
            half_lines = args.exposure_half_lines
            if args.exposure_ms is not None:
                started = time.monotonic()
                first = read()
                first_time = (started + time.monotonic()) / 2
                time.sleep(2)
                started = time.monotonic()
                last = read()
                last_time = (started + time.monotonic()) / 2
                capture_fps = ((last['frames'] - first['frames']) & 0xffffffff) / (last_time - first_time)
                half_lines = sensor_control.from_ms(args.exposure_ms, capture_fps, before['vts'])
                print(json.dumps({'capture_fps_for_exposure': capture_fps, 'requested_ms': args.exposure_ms,
                                  'actual_ms_estimate': 1000*half_lines/(2*before['vts']*capture_fps)}), flush=True)
            if sensor_change:
                restore = json.loads(args.sensor_restore.read_text(encoding='utf-8')) if args.sensor_restore else None
                baseline = root/'config/sensor-history'/f'o1-sensor-before-{time.time_ns()}.json'
                sensor_control.save(baseline, before)
                print(json.dumps({'sensor_baseline': str(baseline)}), flush=True)
                before = sensor_control.apply(sensor, before, half_lines, args.sensor_gain, restore)
            print(json.dumps({'sensor': before}), flush=True)
        if args.view == 'reference' and not current['reference_valid']:
            raise RuntimeError('Set a reference frame first with --frame reference')
        if args.frame in ('play','pause','next') and not current['recorded_frames']:
            raise RuntimeError('Record a clip first with --frame record')
        if args.set or args.view or args.threshold is not None or args.median or args.frame or args.algorithm or args.low_ratio or args.recognition:
            settings = args.set
            widths = [16, 16, 16, 1, 2]
            if args.edge:
                if settings is None:
                    settings = [current[name] for name in
                                ('active_r', 'active_g', 'active_b', 'active_gamma', 'active_phase')]
                requested_view = args.view or ('color','gray','edge','compare','denoise','overlay','reference')[current['ui_view']]
                view = int(requested_view in ('gray', 'compare', 'denoise', 'reference'))
                edge = int(requested_view in ('edge', 'compare', 'denoise', 'reference'))
                settings = [*settings, view, edge]
                threshold = current['threshold_pending'] if args.threshold is None else args.threshold
                algorithm = int(args.algorithm=='canny') if args.algorithm else current['algorithm']
                ratio = ('1/4','1/2','3/4').index(args.low_ratio) if args.low_ratio else current['low_ratio']
                if algorithm and threshold==0:
                    if args.threshold==0:
                        raise ValueError('Canny threshold must be 1..2040')
                    threshold=1
                toggle = current['threshold_ack'] ^ int(args.threshold is not None or threshold!=current['threshold_pending'])
                settings.extend([threshold, toggle])
                widths.extend([1, 1, 11, 1, 1, 1, 1])
                settings.extend([int(args.median=='on') if args.median else current['ui_median'],
                                 int(requested_view=='denoise'), int(requested_view=='overlay')])
                command = {'live':1,'freeze':2,'step':3,'record':4,'play':5,'pause':6,
                           'next':7,'reference':8,'clear-reference':9}.get(args.frame,0)
                if args.frame == 'step' and current['frame_mode'] in (3,4):
                    command = 7
                settings.extend([command, current['frame_command_ack'] ^ int(args.frame is not None),
                                 int(requested_view=='reference'), current['ui_apply_ack'] ^ int(bool(args.view or args.median or args.algorithm or args.low_ratio or args.recognition))])
                widths.extend([4,1,1,1,1,2])
                settings.extend([algorithm,ratio])
                widths.append(1)
                settings.append(int(args.recognition=='on') if args.recognition else current['recognition'])
            manager.vio_write(debug, 'status', [BitSequence(v, length=w)
                for v, w in zip(settings, widths, strict=True)])
            print(json.dumps({'set': settings}), flush=True)
            time.sleep(0.3)
            if args.frame:
                applied = read()
                if applied['ui_busy'] or applied['frame_command_error']:
                    raise RuntimeError(f'Frame command failed or still busy: {applied}')
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
