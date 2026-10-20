"""Evaluate a reviewed manifest through the single frozen reference pipeline."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2

import baseline as b
from compare_hyperlpr import ROOT, OUT
from hyperlpr_reference import FrozenReference
from probe_hyperlpr_rejection import canvas720


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    freeze_path = OUT/'real-rejection/reference-freeze.json'
    freeze = json.loads(freeze_path.read_text(encoding='utf8'))
    for path, digest in freeze['source_hashes'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Frozen reference source changed: {path}')
    manifest = json.loads(args.manifest.read_text(encoding='utf8'))
    args.output.mkdir(exist_ok=False)
    ref = FrozenReference()
    records = []
    for row in manifest['items']:
        path = ROOT/row['path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError(f'Input changed: {path}')
        image = b.read_image(path)
        if row['input_kind'] == 'frame':
            result = ref.run_image(image)
            for i, candidate in enumerate(result['outputs']):
                if 'code' in candidate:
                    import numpy as np
                    crop = ref.warp(canvas720(image), np.array(candidate['points']))
                    cv2.imwrite(str(args.output/f'{row["id"]}-candidate-{i}.png'), crop)
        elif row['input_kind'] == 'patch':
            result = ref.score_patch(image)
            result['accepted'] = result['downstream_accepted']
            result['scope'] = 'Downstream-only ROI test; detector and frame-boundary gates not applicable.'
        else:
            raise ValueError(f'Unknown input kind: {row["input_kind"]}')
        records.append(dict(**row, result=result))
        if result['accepted']:
            cv2.imwrite(str(args.output/f'{row["id"]}-accepted.png'), image)
    summary = {}
    for kind, label in sorted({(r['input_kind'],r['manual_label']) for r in records}):
        group = [r for r in records if r['input_kind']==kind and r['manual_label']==label]
        summary[f'{kind}/{label}'] = dict(total=len(group), accepted=sum(r['result']['accepted'] for r in group),
            unique_file_hashes=len({r['sha256'] for r in group}))
    report = dict(manifest=str(args.manifest), manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        reference_freeze_sha256=hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
        evaluator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        threshold_tuning=False, summary=summary)
    (args.output/'records.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf8')
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
