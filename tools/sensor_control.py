"""SC431HAI manual exposure, using datasheet V1.1 sections 2.4, 2.5 and 2.8."""
import json
import math
import time
from pathlib import Path

EXPOSURE = (0x3e00, 0x3e01, 0x3e02)
GAIN = (0x3e08, 0x3e09)
DIGITAL = (0x3e06, 0x3e07)
GEOMETRY = (0x3208, 0x3209, 0x320a, 0x320b, 0x320c, 0x320d, 0x320e, 0x320f)
REGISTERS = (0x3107, 0x3108, 0x0100, 0x3221, *GEOMETRY, *EXPOSURE, *GAIN, *DIGITAL, 0x3802)
# Keep the DCG/fine-gain combinations from table 2-7; cap at 3.032x.
GAINS = {'1': (0x00, 0x20), '2': (0x80, 0x2a), '3': (0x80, 0x3f)}


class Sensor:
    def __init__(self, manager, debug, bits):
        self.manager, self.debug, self.bits = manager, debug, bits
        self.toggle = self.status() & 1

    def status(self):
        return int(self.manager.vio_read(self.debug, 'snapshot')[3])

    def transfer(self, address, value=None):
        if not self.status() & 4:
            raise RuntimeError('Sensor initialization is not complete')
        self.toggle ^= 1
        command = (self.toggle << 25) | (int(value is not None) << 24) | (address << 8) | (value or 0)
        snapshot = list(map(int, self.manager.vio_read(self.debug, 'snapshot')))
        self.manager.vio_write(self.debug, 'snapshot',
                               [self.bits(63, length=6), self.bits(snapshot[2], length=1),
                                self.bits(command, length=26)])
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = self.status()
            if status & 1 == self.toggle:
                if status & 2:
                    raise RuntimeError(f'Sensor I2C NACK at {address:#06x}')
                return status >> 3
            time.sleep(.01)
        raise TimeoutError(f'Sensor I2C/frame-boundary timeout at {address:#06x}; reload SRAM before retrying')

    def read(self, address):
        return self.transfer(address)

    def write(self, address, value):
        self.transfer(address, value)


def inspect(sensor):
    values = {f'{a:04x}': sensor.read(a) for a in REGISTERS}
    word = lambda a: (values[f'{a:04x}'] << 8) | values[f'{a+1:04x}']
    if word(0x3107) != 0xcd6b:
        raise RuntimeError(f'Unexpected sensor ID {word(0x3107):#06x}')
    if (word(0x3208), word(0x320a), values['3221'], values['0100']) != (2560, 1440, 0x60, 1):
        raise RuntimeError('Expected streaming full-view 2560x1440 with vertical flip; refusing exposure change')
    return {'schema': 1, 'sensor': 'SC431HAI', 'registers': values,
            'half_lines': ((values['3e00'] & 15) << 12) | (values['3e01'] << 4) | (values['3e02'] >> 4),
            'vts': word(0x320e) & 0x7fff, 'hts': word(0x320c)}


def exposure_bytes(half_lines, vts):
    if not isinstance(half_lines, int) or not 4 <= half_lines <= 2 * vts - 11:
        raise ValueError(f'Exposure must be 4..{2*vts-11} half-lines')
    return (half_lines >> 12, (half_lines >> 4) & 255, (half_lines & 15) << 4)


def from_ms(milliseconds, fps, vts):
    if not math.isfinite(milliseconds) or milliseconds <= 0 or not 29.5 <= fps <= 30.5:
        raise ValueError('Positive exposure and measured capture rate 29.5..30.5 fps required')
    count = round(milliseconds * fps * vts * 2 / 1000)
    exposure_bytes(count, vts)
    return count


def save(path, state):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create protects the baseline from accidental replacement.
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
        f.write('\n')


def apply(sensor, before, half_lines=None, gain=None, restore=None):
    old = before['registers']
    desired = {a: old[f'{a:04x}'] for a in (*EXPOSURE, *GAIN, *DIGITAL)}
    if restore is not None:
        if restore.get('schema') != 1 or restore.get('sensor') != 'SC431HAI':
            raise ValueError('Not an O1 SC431HAI saved configuration')
        saved = restore['registers']
        for a in (*GEOMETRY, 0x3221):
            if saved[f'{a:04x}'] != old[f'{a:04x}']:
                raise ValueError('Saved sensor geometry/timing/flip does not match the running sensor')
        desired = {a: saved[f'{a:04x}'] for a in desired}
    elif half_lines is not None:
        desired.update(zip(EXPOSURE, exposure_bytes(half_lines, before['vts'])))
    if gain is not None:
        desired.update(zip(GAIN, GAINS[gain]))
    if any(type(v) is not int or not 0 <= v <= 255 for v in desired.values()):
        raise ValueError('Invalid saved register byte')
    count = ((desired[0x3e00] & 15) << 12) | (desired[0x3e01] << 4) | (desired[0x3e02] >> 4)
    exposure_bytes(count, before['vts'])
    if desired[0x3e00] & 0xf0 or desired[0x3e02] & 15:
        raise ValueError('Invalid exposure register reserved bits')
    # Restore only the supported bounded analog gains and unity digital gain.
    if (desired[0x3e08], desired[0x3e09]) not in GAINS.values() or (desired[0x3e06], desired[0x3e07]) != (0, 0x80):
        raise ValueError('O1 supports 1x/2.021x/3.032x analog and unity digital gain')
    if old['3802'] & 3:
        raise RuntimeError('Unexpected Group Hold frame delay; expected 0')
    try:
        sensor.write(0x3812, 0)
        for address, value in desired.items():
            sensor.write(address, value)
        sensor.write(0x3812, 0x30)
    except Exception as error:
        raise RuntimeError('Exposure transaction failed; do not continue sampling. Reload the known SRAM baseline and restore the saved configuration. Group Hold may remain active.') from error
    # N+2 applies exposure/gain; allow three 30-fps frames before readback.
    time.sleep(.12)
    after = inspect(sensor)
    for address, value in desired.items():
        if after['registers'][f'{address:04x}'] != value:
            raise RuntimeError(f'Exposure readback mismatch at {address:#06x}')
    for address in (*GEOMETRY, 0x3221, 0x0100, 0x3802):
        if after['registers'][f'{address:04x}'] != old[f'{address:04x}']:
            raise RuntimeError(f'Sensor timing/geometry changed at {address:#06x}')
    return after
