"""Build a byte-stream memory oracle without using the reader's unpacking logic."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / 'tmp/blue-plate-frame-reader'
W, H = 1280, 720


def rgb(x, y, seed):
    return bytes(((x * 7 + y * 13 + seed) & 255,
                  (x * 11 + y * 3 + seed * 3) & 255,
                  (x ^ (y * 17) ^ (seed * 13)) & 255))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for seed in (10, 11):
        raw = b''.join(rgb(x, y, seed) for y in range(H) for x in range(W))
        # Independently confirm the existing writer's three-beat packing equations.
        for offset in (0, 48, 4080, len(raw) - 48):
            groups = [int.from_bytes(raw[offset + j:offset + j + 12], 'big')
                      for j in range(0, 48, 12)]
            a, b, c, d = groups
            beats = ((a << 32) | (b >> 64),
                     ((b & ((1 << 64) - 1)) << 64) | (c >> 32),
                     ((c & ((1 << 32) - 1)) << 96) | d)
            assert b''.join(v.to_bytes(16, 'big') for v in beats) == raw[offset:offset + 48]
        path = OUT / f'rgb-{seed}.mem'
        path.write_text(''.join(raw[i:i + 16].hex() + '\n'
                                for i in range(0, len(raw), 16)), encoding='ascii')
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    cases = []
    for x in range(16):
        for width in (1, 2, 3, 15, 16, 17, 319, 320):
            for y in (0, 1, 17, 718):
                cases.append([x, y, width, min(2, H - y)])
    cases += [[960, 624, 320, 96], [1279, 719, 1, 1],
              [80, 1, 17, 3], [84, 1, 17, 3], [85, 1, 17, 3],
              [0, 0, W, H]]
    (OUT / 'cases.txt').write_text(''.join(' '.join(map(str, c)) + '\n' for c in cases), encoding='ascii')
    hashes['cases.txt'] = hashlib.sha256((OUT / 'cases.txt').read_bytes()).hexdigest()
    result = dict(width=W, height=H, seeds=[10, 11], commands=len(cases),
                  byte_phases=sorted({(3 * x) % 16 for x in range(16)}),
                  memory_words=W * H * 3 // 16, sha256=hashes,
                  writer_pack_equations_checked=True)
    (OUT / 'oracle.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
