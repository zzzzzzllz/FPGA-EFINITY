"""Finite synthetic/reference checks against unmodified production RTL."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

import numpy as np
from reference import compute, array_hashes

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RTL = ROOT / "coding/edge-quality-30fps/rtl"
SOURCES = [RTL / (n + ".v") for n in ("median_pair", "gaussian_pair", "sobel_pair",
           "canny_nms_pair", "edge_algorithm_pair", "frame_store_dma")]
PROTECTED = SOURCES + [RTL / "edge_ui.v", RTL / "ti60f225_oob_top.v"]


def hashes(paths):
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def images(w, h):
    y, x = np.indices((h, w))
    mono = lambda a: np.repeat(np.asarray(a, dtype=np.uint8)[..., None], 3, axis=2)
    impulse = np.zeros((h, w), dtype=np.uint8)
    impulse[0, 0] = impulse[0, -1] = impulse[-1, 0] = impulse[-1, -1] = 255
    impulse[h//2, w//2] = 255
    palette = np.array([[0, 0, 0], [255, 255, 255], [255, 0, 0], [0, 255, 0],
                        [0, 0, 255], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.uint8)
    return {
        "black": mono(np.zeros((h, w))), "white": mono(np.full((h, w), 255)),
        "rgb_lanes": palette[(x+3*y) % 8],
        "gray_half_ties": np.array([[128, 0, 0], [0, 0, 128]], dtype=np.uint8)[(x+y) % 2],
        "x_rise": mono((x >= w//2)*255), "x_fall": mono((x < w//2)*255),
        "y_rise": mono((y >= h//2)*255), "y_fall": mono((y < h//2)*255),
        "corner_impulses": mono(impulse), "checker": mono(((x+y) % 2)*255),
        "threshold128": mono((x >= w//2)*32),
        "colored_ramp": np.stack(((71*x+137*y+x*y*13) % 256, (23*x+79*y+5) % 256,
                                  (97*x+7*y+129) % 256), axis=-1).astype(np.uint8),
        "black_after_ramp": mono(np.zeros((h, w))),
    }


def write_mem(path, values, digits):
    path.write_text("".join(f"{int(v):0{digits}x}\n" for v in values), encoding="ascii")


def pair_grad(ref, prefix):
    gx, gy = ref[prefix+"_gx"].ravel(), ref[prefix+"_gy"].ravel()
    return [((int(gx[i]) & 65535) << 48) | ((int(gy[i]) & 65535) << 32) |
            ((int(gx[i+1]) & 65535) << 16) | (int(gy[i+1]) & 65535) for i in range(0, gx.size, 2)]


def run_case(out, name, w, h, stalled, sample_names, configs):
    work = out/name
    work.mkdir(parents=True, exist_ok=True)
    samples = images(w, h)
    vectors = {k: [] for k in ("input", "median", "gauss", "sobel", "a", "b", "gradient", "raw-edge", "settings")}
    records = []
    groups = {}
    for sample_name in sample_names:
        rgb = samples[sample_name]
        for config, recognition in configs:
            ref = compute(rgb, config, recognition)
            for key, field in (("input", "input_rgby"), ("median", "median_rgby"),
                               ("gauss", "a_input_rgby"), ("sobel", "a_output_rgbe")):
                vectors[key].extend(ref[field].ravel().tolist())
            vectors["a"].extend(pair_grad(ref, "a"));vectors["b"].extend(pair_grad(ref, "b"))
            g = (ref["a_direction"].astype(np.uint32)*2048 + ref["a_magnitude"]).ravel()
            vectors["gradient"].extend((g[::2]*8192 + g[1::2]).tolist())
            b = ref["b_edge"].ravel()
            vectors["raw-edge"].extend((b[::2]*2+b[1::2]).tolist())
            vectors["settings"].append(config | (int(recognition) << 16))
            records.append({"sample": sample_name, "config": hex(config), "recognition": recognition,
                            "input": array_hashes({"rgb": rgb}), "outputs": array_hashes(ref)})
            profile = (bool(config & 0x800), bool(config & 0x2000), bool(config & 0x2000) and recognition)
            group = groups.setdefault((sample_name, profile), (ref["a_gx"], ref["a_gy"]))
            if any(not np.array_equal(group[i], ref["a_"+axis]) for i, axis in enumerate(("gx", "gy"))):
                raise AssertionError("flags/threshold/ratio changed A gradient within a profile")
            if any(not np.array_equal(ref["b_"+axis], compute(rgb)["b_"+axis]) for axis in ("gx", "gy")):
                raise AssertionError("B gradient depends on page configuration")
    for key, values in vectors.items():
        write_mem(work/(key+".mem"), values, 16 if key in ("a", "b") else 1 if key=="raw-edge" else 5 if key=="settings" else 7 if key=="gradient" else 8)
    (work/"vectors.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    simulator = ROOT/"tools/iverilog-12/app/bin"
    cmd = [str(simulator/"iverilog.exe"), "-g2012", "-s", "tb_gradients", f"-Ptb_gradients.W={w}",
           f"-Ptb_gradients.H={h}", f"-Ptb_gradients.JOBS={len(records)}", f"-Ptb_gradients.STALL={int(stalled)}",
           "-o", "sim.vvp", *map(str, SOURCES), str(HERE/"tb_gradients.sv")]
    compiled = subprocess.run(cmd, cwd=work, text=True, capture_output=True, timeout=30)
    (work/"compile.log").write_text(compiled.stdout+compiled.stderr, encoding="utf-8")
    compiled.check_returncode()
    simcmd = [str(simulator/"vvp.exe"), "sim.vvp", "+directory=."]
    run = subprocess.run(simcmd, cwd=work, text=True, capture_output=True, timeout=90)
    (work/"simulation.log").write_text(run.stdout+run.stderr, encoding="utf-8")
    print(run.stdout.strip(), flush=True)
    run.check_returncode()
    if not run.stdout.startswith("PASS "):
        raise AssertionError("missing PASS")
    metrics = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", run.stdout)}
    for prefix in ("a", "b"):
        if (work/(prefix+".mem")).read_bytes() != (work/("observed-"+prefix+".mem")).read_bytes():
            raise AssertionError("observed gradient bytes mismatch: "+prefix)
    return {"name": name, "dimensions": [h, w], "jobs": len(records), "stalled": stalled,
            "metrics": metrics, "compile_command": cmd, "simulation_command": simcmd,
            "cwd": str(work), "hashes": hashes(list(work.glob("*.mem"))+[work/"vectors.json", work/"simulation.log"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT/"tmp/blue-plate-edge-gradient-reference")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve();out.mkdir(parents=True, exist_ok=True)
    frozen = hashes(PROTECTED)
    (out/"source-hashes.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    # All M/C/R/comparison combinations plus strict-threshold and low-ratio cases.
    configs = [(0x4038 | (m<<11) | (d<<12) | (c<<13), bool(r))
               for m in range(2) for d in range(2) for c in range(2) for r in range(2)]
    configs += [(0x4000+t, False) for t in (0, 127, 128, 129, 2047)]
    configs += [(0x2838 | (ratio<<14), False) for ratio in (0, 2, 3)]
    smoke_configs = [(0x4038, False), (0x5838, False), (0x6838, False), (0x6838, True)]
    runs = []
    if args.smoke:
        runs.append(run_case(out, "smoke", 16, 12, True, ["colored_ramp", "white", "black_after_ramp"], smoke_configs))
    else:
        sample_names = list(images(16, 12))
        runs.append(run_case(out, "small-stall", 16, 12, True, sample_names, configs))
        runs.append(run_case(out, "small-flow", 16, 12, False, sample_names, configs))
        runs.append(run_case(out, "nonpower-width", 6, 4, True, ["colored_ramp", "corner_impulses", "black_after_ramp"], smoke_configs))
        runs.append(run_case(out, "full-width-short", 1280, 6, True, ["colored_ramp", "corner_impulses", "black_after_ramp"], smoke_configs))
    if hashes(PROTECTED) != frozen:
        raise AssertionError("production RTL changed during validation")
    # Tiny images may fit inside all five windows before downstream backpressure
    # propagates. Require each stall condition across the suite, not every image size.
    for field in ("A_stalls", "B_stalls", "M_stalls", "G_stalls", "O_stalls", "eol_stalls", "eof_stalls"):
        if sum(r["metrics"][field] for r in runs) == 0:
            raise AssertionError("missing suite coverage: "+field)
    result = {"status": "PASS", "scope": "finite synthetic grayscale/gradient reference only; no localization, OCR, mapping or board run",
              "runs": runs, "source_hashes": frozen,
              "reference_hashes": hashes([HERE/"reference.py", HERE/"tb_gradients.sv", Path(__file__)]),
              "jobs": sum(x["jobs"] for x in runs), "pixels_per_tap": sum(x["metrics"]["pixels"] for x in runs)}
    (out/("smoke-report.json" if args.smoke else "report.json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "jobs", "pixels_per_tap")}), flush=True)


if __name__ == "__main__":
    main()
