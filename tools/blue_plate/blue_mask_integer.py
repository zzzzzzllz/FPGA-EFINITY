"""Exact integer form of the existing OpenCV blue mask, with a runnable audit.

Reference: OpenCV 4.11.0 color_hsv.simd.hpp RGB2HSV_b and histogram.cpp
equalizeHist. This does not change baseline.py or implement the locator's CCL.
"""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def round_ratio(n, d):
    q, r = divmod(n, d)
    return q + int(2*r > d or (2*r == d and q & 1))


def ceil_ratio(n, d):
    return -((-n)//d)


def blue_tables():
    saturation = np.zeros((256, 2), np.int16)
    hue = np.zeros((256, 2), np.int16)
    saturation[0] = hue[0] = [1, 0]
    for x in range(1, 256):
        sd = round_ratio(255 << 12, x)
        hd = round_ratio(180 << 12, 6*x)
        saturation[x] = [ceil_ratio(96*4096-2048, sd), (255*4096-2049)//sd]
        hue[x] = [ceil_ratio(101*4096-2048, hd)-4*x, (140*4096-2049)//hd-4*x]
    return saturation, hue


SATURATION, HUE = blue_tables()


def blue_hs(image):
    b, g, r = [image[..., k].astype(np.int16) for k in range(3)]
    # Hue 101..139 implies a strict blue maximum. The exhaustive audit checks
    # that implication, including ties and both ends of each threshold.
    d = b - np.minimum(r, g)
    z = r - g
    hue = HUE[np.maximum(d, 0)]
    sat = SATURATION[b]
    return ((b > r) & (b > g) & (d >= sat[..., 0]) & (d <= sat[..., 1]) &
            (z >= hue[..., 0]) & (z <= hue[..., 1]))


def scale_float32_integer(denominator):
    """Return integer mantissa, power for correctly rounded float32(255/N)."""
    exponent = 255 .bit_length() - denominator.bit_length()
    if exponent >= 0:
        exponent -= int(255 < denominator << exponent)
    else:
        exponent -= int((255 << -exponent) < denominator)
    shift = 23-exponent
    mantissa = round_ratio(255 << shift, denominator)
    return mantissa, exponent-23


def equalized_lut(histogram):
    """Emulate the two binary32 rounding steps using integer arithmetic only.

    The source uses float32 scale=255/N, then float32(cumulative*scale), then
    nearest-even conversion to uint8. A single rational division is different.
    """
    hist = [int(x) for x in histogram]
    if len(hist) != 256 or any(x < 0 for x in hist):
        raise ValueError('Expected 256 nonnegative histogram counts')
    total = sum(hist)
    if not 1 <= total <= 1280*720:
        raise ValueError('Histogram must contain 1..921600 pixels')
    first = next(i for i, count in enumerate(hist) if count)
    lut = np.zeros(256, np.uint8)
    if hist[first] == total:
        lut[first] = first  # OpenCV preserves a constant image's input value.
        return lut
    mantissa, power = scale_float32_integer(total-hist[first])
    cumulative = 0
    for i in range(first+1, 256):
        cumulative += hist[i]
        product = cumulative*mantissa
        discarded = max(0, product.bit_length()-24)
        significand = round_ratio(product, 1 << discarded)
        result_power = power+discarded
        value = (significand << result_power if result_power >= 0 else
                 round_ratio(significand, 1 << -result_power))
        lut[i] = min(value, 255)
    return lut


def blue_mask(image):
    value = image.max(axis=2)
    lut = equalized_lut(np.bincount(value.ravel(), minlength=256))
    accepted_value = (lut > 95) & (lut < 255)
    return blue_hs(image) & accepted_value[value]


def audit_rgb():
    r, g = np.indices((256, 256), dtype=np.uint8)
    image = np.empty((256, 256, 3), np.uint8)
    image[..., 1], image[..., 2] = g, r
    accepted = 0
    for b in range(256):
        image[..., 0] = b
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        expected = ((hsv[..., 0] > 100) & (hsv[..., 0] < 140) &
                    (hsv[..., 1] > 95) & (hsv[..., 1] < 255))
        actual = blue_hs(image)
        if np.any(actual != expected):
            where = np.argwhere(actual != expected)[0]
            raise AssertionError(f'HSV mismatch B={b}, R/G={where.tolist()}')
        accepted += int(expected.sum())
    return dict(rgb_combinations=256**3, differences=0, accepted=accepted)


def audit_histograms():
    rng = np.random.default_rng(601018)
    cases = [np.eye(1, 256, i, dtype=np.int64).ravel()*921600 for i in range(256)]
    for _ in range(256):
        n = int(rng.integers(1, 921601))
        p = rng.random(256)
        p[rng.random(256) < .75] = 0
        cases.append(rng.multinomial(n, p/p.sum()))
    # Concentrate cumulative sums around both acceptance boundaries.
    for denominator in [255, 510, 65535, 65536, 100000, 921599]:
        for boundary in [95.5, 254.5]:
            center = round(denominator*boundary/255)
            for delta in range(-4, 5):
                cumulative = max(0, min(denominator, center+delta))
                hist = np.zeros(256, np.int64)
                hist[[0, 100, 200]] = [1, cumulative, denominator-cumulative]
                cases.append(hist)
    pixels = 0
    for hist in cases:
        values = np.repeat(np.arange(256, dtype=np.uint8), hist)
        expected = cv2.equalizeHist(values[:, None]).ravel()
        actual = equalized_lut(hist)[values]
        if not np.array_equal(actual, expected):
            raise AssertionError(f'Equalization mismatch in histogram case {pixels}')
        pixels += len(values)
    return dict(histograms=len(cases), pixels=pixels, differences=0)


def audit_frames():
    manifest = ROOT/'tmp/blue-plate-normal-g1/full-dual-local-geometry/samples.json'
    records = json.loads(manifest.read_text(encoding='utf8'))
    hashes = []
    for record in records:
        if record['split'] == 'heldout':
            continue
        path = ROOT/record['path']
        data = path.read_bytes()
        source = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if source is None:
            raise ValueError(f'Cannot decode {path}')
        h, w = source.shape[:2]
        scale = min(1280/w, 720/h)
        nw, nh = round(w*scale), round(h*scale)
        dx, dy = (1280-nw)//2, (720-nh)//2
        image = np.zeros((720, 1280, 3), np.uint8)
        image[dy:dy+nh, dx:dx+nw] = cv2.resize(source, (nw, nh), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        eq = cv2.equalizeHist(hsv[..., 2])
        reference = ((hsv[..., 0] > 100) & (hsv[..., 0] < 140) &
                     (hsv[..., 1] > 95) & (hsv[..., 1] < 255) & (eq > 95) & (eq < 255))
        actual = blue_mask(image)
        if not np.array_equal(reference, actual):
            raise AssertionError(f'Frame mask mismatch {record["path"]}')
        hashes.append(dict(path=record['path'], sha256=hashlib.sha256(data).hexdigest(),
                           mask_sha256=hashlib.sha256(actual.tobytes()).hexdigest()))
        if len(hashes) % 50 == 0:
            print(f'Compared {len(hashes)} frame masks', flush=True)
    return dict(frames=len(hashes), pixels=len(hashes)*1280*720, differences=0,
                heldout_evaluated=0, manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                records=hashes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--frames', action='store_true')
    args = parser.parse_args()
    out = ROOT/'tmp/blue-plate-normal-g1/integer-blue-mask'
    out.mkdir(parents=True, exist_ok=True)
    report = dict(opencv=cv2.__version__, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  rgb=audit_rgb(), equalization=audit_histograms())
    if args.frames:
        report['frames'] = audit_frames()
    np.savez(out/'tables.npz', saturation=SATURATION, hue=HUE)
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v if k != 'frames' else {a:b for a,b in v.items() if a != 'records'}
                      for k,v in report.items()}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
