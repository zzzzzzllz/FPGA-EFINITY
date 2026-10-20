"""Development-only necessary visual structure checks; no OCR/threshold fitting.

The inference function sees only the fixed BGR ROI. Labels, edit kinds and
intervention masks are excluded from its signature and computation.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

import baseline as b
from compare_hyperlpr import ROOT, OUT, SOURCE, inspected_functions
from geometry_sampler import sample_integer
from probe_hyperlpr_fullframe import variants
from probe_hyperlpr_rejection import canvas720

DEST = OUT/'structure-development-v1'
THRESHOLDS = dict(strict=0.9931710550839266, comparison=0.9386077887914179)
RULES = ['global_seven', 'local_seven', 'either_seven', 'both_seven', 'easypr_rows']


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def structure(roi):
    if roi.shape != (64, 224, 3) or roi.dtype != np.uint8:
        raise ValueError('Expected fixed 224x64 uint8 BGR')
    details, masks = {}, {}
    for mode in ['global', 'local']:
        chars, mask, rects = b.segment(roi, mode, 'projection-char')
        projection = mask.sum(axis=0)
        # Existing windows, cuts, row cleanup and dimensions remain unchanged.
        cuts = [4] + [min(range(c-9, c+10), key=lambda x:(int(projection[x]), abs(x-c), x))
                      for c in [34, 70, 101, 132, 163, 194]] + [220]
        cells = []
        for left, right in zip(cuts, cuts[1:]):
            yy, xx = np.where(mask[:, left:right])
            cells.append(dict(left=left, right=right, white_pixels=int(len(xx)),
                height=int(yy.max()-yy.min()+1) if len(xx) else 0,
                width=int(xx.max()-xx.min()+1) if len(xx) else 0))
        details[mode] = dict(pass_gate=len(chars) == 7, measured_rects=[list(map(int, r)) for r in rects],
            cuts=cuts, valley_counts=[int(projection[x]) for x in cuts[1:-1]], cells=cells,
            min_cell_height=min(c['height'] for c in cells), min_cell_white=min(c['white_pixels'] for c in cells))
        masks[mode] = mask
    # Diagnostic reproduction of EasyPR spatial_ostu(8,2,BLUE)/clearLiuDing
    # aggregate criteria. These upstream thresholds are not completeness proof.
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    spatial = np.zeros((64, 224), np.uint8)
    for y in range(0, 64, 32):
        for x in range(0, 224, 28):
            spatial[y:y+32, x:x+28] = cv2.threshold(gray[y:y+32, x:x+28], 0, 255, cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]//255
    jumps = np.count_nonzero(np.diff(spatial.astype(np.int16), axis=1), axis=1)
    qualifying = int(np.count_nonzero((jumps >= 16) & (jumps <= 45)))
    white = int(spatial[:, :-1].sum())  # Match upstream's last-column exclusion.
    row_pass = qualifying/64 > .40 and .15 <= white/(64*224) <= .50
    masks['spatial'] = spatial
    flags = dict(global_seven=details['global']['pass_gate'], local_seven=details['local']['pass_gate'],
                 either_seven=details['global']['pass_gate'] or details['local']['pass_gate'],
                 both_seven=details['global']['pass_gate'] and details['local']['pass_gate'], easypr_rows=row_pass)
    return dict(rules=flags, projection=details, easypr=dict(qualifying_rows=qualifying, white_pixels=white,
                white_fraction=white/(64*224), row_fraction=qualifying/64)), masks


def choose(candidates, threshold, rule=None):
    allowed = [p for p in candidates if p['ocr']['legal'] and p['ocr']['score'] >= threshold and p['base_gate']
               and (rule is None or p['structure']['rules'][rule])]
    best = max(allowed, key=lambda p:(p['ocr']['score'], -p['candidate_index']), default=None)
    return None if best is None else dict(code=best['ocr']['code'], score=best['ocr']['score'], candidate_index=best['candidate_index'])


def main():
    DEST.mkdir(exist_ok=False)
    cv2.setNumThreads(2)
    dev_dir = ROOT/'tmp/blue-plate-char-segment'
    dependencies = [Path(__file__), Path(b.__file__), Path('tools/blue_plate/geometry_sampler.py'),
        Path('tools/blue_plate/probe_hyperlpr_fullframe.py'),
        ROOT/'tmp/plate-research/easypr_chars_segment.cpp',
        OUT/'easypr-judge/src/core/core_func.cpp', OUT/'easypr-judge/src/core/plate_judge.cpp',
        dev_dir/'experiment/dev-manifest.json', dev_dir/'experiment/dev-inputs.npz',
        dev_dir/'pretrained-new-rois/q8_bgr-roi-records.json', dev_dir/'pretrained-new-rois/gates.json',
        OUT/'lpr-rejection/records.json', OUT/'comparison-records.json']
    hashes = {str(p): sha(p) for p in dependencies}
    assert sha(Path(b.__file__)) == '2329329c2b90f22bb7554713b36c4771d90a015d73bdc4ee4233319b574e0a89'
    write(DEST/'protocol-before-evaluation.json', dict(source_hashes=hashes, rules=RULES,
        primary='global_seven; local and either/both are predefined comparisons, not sequential threshold tuning',
        reuse='baseline.segment(global/local, projection-char); no old character recognition',
        upstream_diagnostic='spatial_ostu 8x2 256-bin Otsu; clearLiuDing row and density checks only',
        exclusions=['verifyCharSizes integer percPixels', 'inferred Chinese box as evidence', 'OCR character identities', 'edit masks', 'labels in inference'],
        thresholds=THRESHOLDS, data='304 dev positive + 912 dev edits + 107 existing real records',
        validation_evaluated=0, heldout_read=0, threshold_fit=False,
        base_gate='Frozen native learned blue/HS and raw frame boundaries; fixed new LPRNet scores'))
    frames = []
    positive_rois = np.load(dev_dir/'experiment/dev-inputs.npz')['bgr']
    manifest = read(dev_dir/'experiment/dev-manifest.json')['records']
    ocr = read(dev_dir/'pretrained-new-rois/q8_bgr-roi-records.json')
    gates = read(dev_dir/'pretrained-new-rois/gates.json')
    groups = {}
    evidence = []

    def inspect(image, record, pred, base_gate):
        detail, masks = structure(image)
        p = dict(**record, ocr=pred, base_gate=bool(base_gate), structure=detail)
        evidence.append(dict(**{k: record[k] for k in ['input_id', 'candidate_index']}, structure=detail))
        return p, masks

    for m, image, pred, gate in zip(manifest, positive_rois, ocr, gates):
        assert m['original_split'] == 'development' and m['roi_index'] == pred['roi_index'] == gate['roi_index']
        assert hashlib.sha256(image.tobytes()).hexdigest() == m['roi_bgr_sha256']
        index = m['sample_index']
        frame = groups.setdefault(index, dict(id=f'dev-positive-{index}', input_kind='frame', kind='positive',
            label=m['source_transcript'], sample_index=index, path=m['path'], outputs=[]))
        p, masks = inspect(image, dict(input_id=frame['id'], candidate_index=m['candidate_index'], dev_roi_index=m['roi_index']), pred, gate['combined_pass'])
        frame['outputs'].append(p)
        if gate['combined_pass'] and pred['legal'] and pred['score'] >= THRESHOLDS['strict'] and not detail_pass(p):
            cv2.imwrite(str(DEST/f'dev-{index}-roi-{m["candidate_index"]}.png'), image)
            for name, mask in masks.items():
                cv2.imwrite(str(DEST/f'dev-{index}-roi-{m["candidate_index"]}-{name}.png'), mask*255)
    assert len(groups) == 304 and len(manifest) == 307
    frames.extend(groups.values())
    old = {r['id']: r for r in read(OUT/'lpr-rejection/records.json') if r['split'] in ['development', 'seen_real_diagnostic']}
    warp = inspected_functions(SOURCE/'common/tools_process.py', ['get_rotate_crop_image'])['get_rotate_crop_image']

    def negative(image, row):
        frame = dict(id=row['id'], input_kind=row['input_kind'], kind=row['kind'], path=row['path'], outputs=[])
        for prev in row['outputs']:
            if 'ocr' not in prev:
                continue
            fixed, _ = sample_integer(image, np.array(prev['points']), 32, integer_solver=True)
            assert hashlib.sha256(fixed.tobytes()).hexdigest() == prev['bgr_sha256']
            gate = prev['boundary_pass'] is not False and prev['native_color']['color_class'] == 0 and prev['native_color']['hs_pass']
            p, masks = inspect(fixed, dict(input_id=frame['id'], candidate_index=prev['candidate_index'],
                               prior_roi_index=prev['roi_index']), prev['ocr'], gate)
            frame['outputs'].append(p)
            if gate and prev['ocr']['strict_accepts']:
                cv2.imwrite(str(DEST/f'negative-{prev["roi_index"]}.png'), fixed)
                for name, mask in masks.items():
                    cv2.imwrite(str(DEST/f'negative-{prev["roi_index"]}-{name}.png'), mask*255)
        frames.append(frame)
        if len(frames) % 100 == 0:
            print(f'Structure evaluated {len(frames)}/1323 inputs', flush=True)

    for original in read(OUT/'comparison-records.json'):
        if original['split'] != 'development':
            continue
        frame = canvas720(b.read_image(ROOT/original['path']))
        anchor = max(original['detector320'], key=lambda p:p['detector_confidence'])
        for kind, image, _ in variants(frame, np.array(anchor['points']), warp):
            if kind != 'positive':
                negative(image, old[f'{original["sample_index"]}-{kind}'])
    for row in old.values():
        if row['split'] == 'seen_real_diagnostic':
            image = b.read_image(ROOT/row['path'])
            negative(image if row['input_kind'] == 'patch' else canvas720(image), row)
    assert len(frames) == 1323
    for frame in frames:
        frame['selections'] = {f'{level}/{rule}': choose(frame['outputs'], threshold, None if rule == 'base' else rule)
            for level, threshold in THRESHOLDS.items() for rule in ['base']+RULES}
    summary = {}
    for input_kind, kind in sorted({(r['input_kind'], r['kind']) for r in frames}):
        group = [r for r in frames if (r['input_kind'], r['kind']) == (input_kind, kind)]
        metrics = {}
        for key in group[0]['selections']:
            selected = [(r, r['selections'][key]) for r in group]
            stats = dict(accepted=sum(s is not None for r, s in selected))
            if kind == 'positive':
                stats.update(correct=sum(s is not None and s['code'] == r['label'] for r, s in selected),
                             wrong=sum(s is not None and s['code'] != r['label'] for r, s in selected))
            metrics[key] = stats
        summary[f'{input_kind}/{kind}'] = dict(inputs=len(group), metrics=metrics)
    assert summary['frame/positive']['metrics']['strict/base'] == dict(accepted=249, correct=249, wrong=0)
    assert hashes == {str(p): sha(p) for p in dependencies}
    write(DEST/'records.json', frames)
    write(DEST/'report.json', dict(summary=summary, inputs=len(frames), rois=len(evidence), validation_evaluated=0, heldout_read=0))
    write(DEST/'artifacts.json', {p.name: sha(p) for p in DEST.iterdir() if p.is_file() and p.suffix in ['.json', '.py'] and p.name != 'artifacts.json'})
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def detail_pass(p):
    return p['structure']['rules']['both_seven']


if __name__ == '__main__':
    main()
