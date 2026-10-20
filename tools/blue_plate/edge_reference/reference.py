"""Integer A/B gradient reference for the original edge-quality-30fps RTL."""
from pathlib import Path
import argparse
import hashlib
import json

import numpy as np


def ddr_luma(rgb):
    """RGB uint8 HWC -> Y; matches frame_store_dma.luma, not OpenCV cvtColor."""
    rgb = np.asarray(rgb)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected uint8 RGB array with shape (height, width, 3)")
    if rgb.shape[0] < 2 or rgb.shape[1] < 4 or rgb.shape[1] % 2:
        raise ValueError("RTL reference requires height >= 2 and even width >= 4")
    r, g, b = np.moveaxis(rgb.astype(np.int32), -1, 0)
    return ((77*r + 150*g + 29*b + 128) >> 8).astype(np.uint8)


def windows(gray):
    h, w = gray.shape
    padded = np.pad(gray.astype(np.int32), 1, mode="edge")
    return [padded[y:y+h, x:x+w] for y in range(3) for x in range(3)]


def gradient(gray, threshold):
    a, b, c, d, _, f, g, h, i = windows(gray)
    gx = c + 2*f + i - a - 2*d - g
    gy = g + 2*h + i - a - 2*b - c
    ax, ay = abs(gx), abs(gy)
    magnitude = ax + ay
    direction = np.where(ay*256 <= ax*106, 0,
                         np.where(ay*106 >= ax*256, 1,
                                  np.where((gx < 0) == (gy < 0), 2, 3)))
    edge = (magnitude > threshold).astype(np.uint8)
    edge[[0, -1], :] = 0
    edge[:, [0, -1]] = 0
    return dict(gx=gx.astype("<i2"), gy=gy.astype("<i2"),
                magnitude=magnitude.astype("<u2"), direction=direction.astype(np.uint8),
                edge=edge)


def compute(rgb, config=0x4038, recognition=False):
    """Return both taps in full-image coordinates, with raw signed border gradients.

    config: [10:0] threshold, [11] median, [12] comparison payload,
    [13] Canny smoothing, [15:14] Canny low ratio (does not affect gradients).
    recognition selects a box filter only when bit 13 is set.
    No frame timing, localization, NMS, hysteresis or OCR is modeled here.
    """
    if not isinstance(config, (int, np.integer)) or not 0 <= config <= 0xffff:
        raise ValueError("config must be an unsigned 16-bit integer")
    if not isinstance(recognition, (bool, np.bool_)):
        raise ValueError("recognition must be boolean")
    gray = ddr_luma(rgb)
    median = (np.partition(np.stack(windows(gray)), 4, axis=0)[4]
              if config & 0x800 else gray.astype(np.int32))
    smooth = median
    if config & 0x2000:
        neighborhood = windows(median)
        if recognition:
            smooth = (sum(neighborhood) + 4) // 9
        else:
            smooth = (sum(k*v for k, v in zip((1, 2, 1, 2, 4, 2, 1, 2, 1), neighborhood)) + 8) >> 4
    a, b = gradient(smooth, config & 0x7ff), gradient(gray, config & 0x7ff)
    result = {"b_gray": gray, "median_y": median.astype(np.uint8), "a_gray": smooth.astype(np.uint8)}
    result.update({"a_"+k: v for k, v in a.items()})
    result.update({"b_"+k: v for k, v in b.items()})
    # Test/adaptation payloads: each uint32 is {Y or edge byte, R, G, B}.
    rgb32 = rgb.astype(np.uint32)
    color = (rgb32[..., 0] << 16) | (rgb32[..., 1] << 8) | rgb32[..., 2]
    result["input_rgby"] = (gray.astype(np.uint32) << 24) | color
    result["median_rgby"] = (median.astype(np.uint32) << 24) | color
    payload = ((gray.astype(np.uint32) << 16) | (median.astype(np.uint32) << 8) | (b["edge"].astype(np.uint32)*255)
               if config & 0x1000 else color)
    result["a_input_rgby"] = (smooth.astype(np.uint32) << 24) | payload
    result["a_output_rgbe"] = (a["edge"].astype(np.uint32)*255 << 24) | payload
    return result


def array_hashes(arrays):
    """Hash C-order bytes; shape and endian-aware dtype are part of the manifest."""
    return {name: {"shape": list(a.shape), "dtype": a.dtype.str,
                   "sha256": hashlib.sha256(a.tobytes(order="C")).hexdigest()}
            for name, a in arrays.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True, help="uint8 RGB HWC .npy")
    p.add_argument("--output", type=Path, required=True, help="output .npz")
    p.add_argument("--config", type=lambda x: int(x, 0), default=0x4038)
    p.add_argument("--recognition", action="store_true")
    args = p.parse_args()
    rgb = np.load(args.input, allow_pickle=False)
    arrays = compute(rgb, args.config, args.recognition)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez(args.output, **arrays)
    args.output.with_suffix(".json").write_text(json.dumps({
        "input": str(args.input.resolve()), "input_file_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "config": args.config, "recognition": args.recognition,
        "input_array": array_hashes({"rgb": rgb}), "outputs": array_hashes(arrays),
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
