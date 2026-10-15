"""Read one immutable M10 status snapshot through its separate VIO core."""
import time


def read_snapshot(manager, debug, layout, bit_sequence):
    initial = list(map(int, manager.vio_read(debug, 'snapshot')))
    capture = initial[2] ^ 1
    # Keep the sensor request equal to its ack: ordinary status reads do no I2C.
    sensor_idle = (initial[3] & 1) << 25
    packed = 0
    for page in range(layout['pages']):
        manager.vio_write(debug, 'snapshot',
                          [bit_sequence(page, length=6), bit_sequence(capture, length=1),
                           bit_sequence(sensor_idle, length=26)])
        deadline = time.monotonic() + 2
        while True:
            data, page_ack, capture_ack, _ = map(int, manager.vio_read(debug, 'snapshot'))
            if page_ack == page and capture_ack == capture:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f'Status snapshot page {page} was not acknowledged')
        packed |= data << (page * layout['page_width'])
    return {p['name']: (packed >> p['offset']) & ((1 << p['width']) - 1)
            for p in layout['probes']}
