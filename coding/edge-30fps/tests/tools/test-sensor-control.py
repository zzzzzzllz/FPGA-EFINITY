"""Check grouped exposure updates, validation, readback and failure reporting offline."""
import copy
import tempfile
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'tools'))
import sensor_control as sc


class MockSensor:
    def __init__(self):
        self.registers = dict.fromkeys(sc.REGISTERS, 0)
        self.registers.update({0x3107: 0xcd, 0x3108: 0x6b, 0x0100: 1, 0x3221: 0x60,
            0x3208: 10, 0x3209: 0, 0x320a: 5, 0x320b: 0xa0, 0x320c: 5, 0x320d: 0x78,
            0x320e: 5, 0x320f: 0xdc, 0x3e01: 0xba, 0x3e02: 0xd0,
            0x3e08: 0x80, 0x3e09: 0x2a, 0x3e07: 0x80})
        self.writes, self.group, self.fail, self.mismatch = [], None, None, False

    def read(self, address):
        return self.registers[address] ^ int(self.mismatch and address == 0x3e01)

    def write(self, address, value):
        if address == self.fail:
            raise RuntimeError('injected NACK')
        self.writes.append((address, value))
        if address == 0x3812:
            if value == 0:
                assert self.group is None
                self.group = {}
            else:
                assert value == 0x30 and self.group is not None and len(self.group) <= 10
                self.registers.update(self.group)
                self.group = None
        else:
            assert self.group is not None
            self.group[address] = value


def rejects(fn, kind):
    try:
        fn()
    except kind:
        return
    raise AssertionError('Expected rejection')


with patch.object(sc.time, 'sleep'):
    sensor = MockSensor()
    baseline = sc.inspect(sensor)
    assert baseline['half_lines'] == 2989 and baseline['vts'] == 1500
    for ms in (1, 2, 5, 10, 20, 30):
        count = sc.from_ms(ms, 30, 1500)
        after = sc.apply(sensor, sc.inspect(sensor), count, '2')
        assert after['half_lines'] == 90 * ms
        assert sensor.writes[-9] == (0x3812, 0) and sensor.writes[-1] == (0x3812, 0x30)
    assert sc.apply(sensor, sc.inspect(sensor), restore=baseline)['registers'] == baseline['registers']
    for count in (0, 3, 2990, 65535):
        rejects(lambda: sc.apply(sensor, baseline, count), ValueError)
    for fps in (0, 13.93, 60):
        rejects(lambda: sc.from_ms(10, fps, 1500), ValueError)
    broken = copy.deepcopy(baseline)
    broken['registers']['320f'] = 0xdd
    rejects(lambda: sc.apply(sensor, baseline, restore=broken), ValueError)
    before_writes = len(sensor.writes)
    broken['registers']['320f'] = 0xdc
    broken['registers']['3e08'] = 0xff
    rejects(lambda: sc.apply(sensor, baseline, restore=broken), ValueError)
    assert len(sensor.writes) == before_writes
    sensor.fail = 0x3e01
    rejects(lambda: sc.apply(sensor, baseline, 900), RuntimeError)
    assert sensor.group is not None and sensor.registers[0x3e01] == 0xba
    sensor = MockSensor()
    sensor.mismatch = True
    rejects(lambda: sc.apply(sensor, baseline, 900), RuntimeError)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)/'sensor-history'/'saved.json'
        sc.save(path, baseline)
        rejects(lambda: sc.save(path, baseline), FileExistsError)
print('PASS O1: grouped updates, six exposure values, restore, invalid input, NACK and readback mismatch')


class MockManager:
    response = 4
    fail = False
    def vio_read(self, debug, core):
        assert core == 'snapshot'
        return [0, 63, 1, self.response]
    def vio_write(self, debug, core, values):
        assert core == 'snapshot' and values[:2] == [63, 1]
        self.command = values[2]
        self.response = (0xcd << 3) | 4 | (int(self.fail) << 1) | (self.command >> 25)


manager = MockManager()
transport = sc.Sensor(manager, None, lambda v, length: v)
assert transport.read(0x3107) == 0xcd
assert manager.command == (1 << 25) | (0x3107 << 8)
transport.write(0x3812, 0x30)
assert manager.command == (1 << 24) | (0x3812 << 8) | 0x30
manager.fail = True
rejects(lambda: transport.read(0x3108), RuntimeError)
print('PASS O1 host transport: snapshot preserved, request toggles, register packing, NACK surfaced')
