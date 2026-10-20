"""Prepare once, then evaluate every E1 cached hypothesis once."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from completeness_c1 import RULES, check, components, inspect_context, edges_at_pixels
from bounded_edge_locator import STRUCTURE, array_hash, sample_integer
from edge_local_refine import gray_from_bgr
from run_edge_localization import ROOT, BASE, OUT as E0, read, write_new, hashes, verify_hashes
from run_edge_local_e1 import OUT as E1

OUT = BASE / 'completeness-c1'
DOC = ROOT / 'docs/validation/blue-plate/char-segment/completeness-c1-contract.md'
CONTRACT = dict(version='C1-contextual-frozen-quad', rules=RULES, frames=304,
    coarse_cache_arrays=373, final_cache_arrays=157, original_image_reads=0,
    localization_calls=0, model_forwards=0, training=0, validation84_reads=0, heldout112_reads=0,
    complete_certification=False, ambiguity_promotion=False,
    synthetic_templates=8, synthetic_cut_fraction=[1,4], synthetic_polarities=['light','dark'],
    synthetic_cases=['uncut','top','bottom','left','right','border_only','connected_border'])


def prepare():
    if OUT.exists():
        raise FileExistsError(OUT)
    verify_hashes(read(E1/'delivery-freeze.json')['artifacts'])
    verify_hashes(read(E0/'delivery-freeze.json')['artifacts'])
    sources = [Path(__file__), Path(__file__).with_name('completeness_c1.py'), DOC,
        Path(__file__).with_name('bounded_edge_locator.py'), Path(__file__).with_name('edge_local_refine.py'),
        Path(__file__).with_name('run_edge_localization.py'), Path(__file__).with_name('run_edge_local_e1.py'),
        ROOT/'tools/blue_plate/geometry_sampler.py', ROOT/'tools/blue_plate/baseline.py',
        E1/'delivery-freeze.json', E0/'delivery-freeze.json']
    research = BASE/'completeness-research'
    sources.extend(sorted((research/'openalpr').rglob('*.*')))
    sources.extend([research/'openalpr/LICENSE', research/'acquisition.json', research/'acquire.py'])
    OUT.mkdir()
    write_new(OUT/'identities.json', read(E1/'identities.json'))
    write_new(OUT/'contract.json', CONTRACT)
    write_new(OUT/'source-hashes.json', hashes(sources))
    write_new(OUT/'preparation.json', dict(status='FROZEN_BEFORE_CACHE_ARRAY_EVALUATION',
        created_utc=datetime.now(timezone.utc).isoformat(),
        files=hashes([OUT/'identities.json', OUT/'contract.json', OUT/'source-hashes.json'])))
    print('C1 frozen before synthetic controls and all 157 cache hypotheses')


def controls(templates):
    records = []
    for identity, stencil in templates:
        height, width = stencil.shape
        for polarity in ('light','dark'):
            for case in CONTRACT['synthetic_cases']:
                ink = np.zeros((120, 320), bool)
                original_seeds = []
                for i in range(7):
                    x = 20+40*i
                    seed = np.zeros_like(ink)
                    seed[30:30+height,x:x+width] = stencil
                    original_seeds.append(seed)
                    ink |= seed
                left, top, right, bottom = 17, 27, 20+240+width+2, 30+height+2
                if case == 'top': top = 30+max(1,height//4)
                if case == 'bottom': bottom = 30+height-max(1,height//4)-1
                if case == 'left': left = 20+max(1,width//4)
                if case == 'right': right = 20+240+width-max(1,width//4)-1
                if case in ('border_only', 'connected_border'):
                    ink[top, left:right+1] = True
                    ink[bottom, left:right+1] = True
                    ink[top:bottom+1, left] = True
                    ink[top:bottom+1, right] = True
                if case == 'connected_border':
                    # Connect every actual stencil to the top frame: it becomes ambiguous background/ink.
                    for s in original_seeds:
                        y, x = np.argwhere(s)[0]
                        ink[top:y+1, x] = True
                points = np.array([[left,top],[right,top],[right,bottom],[left,bottom]])
                q16 = (points*65536).tolist()
                cross, _ = edges_at_pixels(ink.shape, q16, (0,0))
                interior = np.all(cross >= 0, axis=0)
                seeds = [s & interior for s in original_seeds]
                assert all(s.any() for s in seeds)
                gray = np.where(ink, 224, 16).astype(np.uint8)
                if polarity == 'dark': gray = 255-gray
                bgr = np.repeat(gray[:,:,None], 3, axis=2)
                final, _ = sample_integer(bgr, points.astype(float), integer_solver=True)
                final_gray = gray_from_bgr(final)
                target = gray
                if polarity == 'dark':
                    final_gray, target = 255-final_gray, 255-target
                mask = STRUCTURE['otsu32'](final_gray, target=target)
                assert mask is not None
                result = inspect_context(mask, seeds, height, q16, (0,0))
                expected = case in ('top','bottom','left','right')
                records.append(dict(template_sample=identity, stencil_sha256=array_hash(stencil),
                    polarity=polarity, case=case, known_cut=expected, reject=result['reject'],
                    expected_behavior_met=result['reject'] == expected, result=result))
    assert len(records) == 112
    return records


def run():
    verify_hashes(read(OUT/'preparation.json')['files'])
    verify_hashes(read(OUT/'source-hashes.json'))
    assert read(OUT/'contract.json') == CONTRACT
    write_new(OUT/'run-start.json', dict(started_utc=datetime.now(timezone.utc).isoformat(),
        fresh_original_images=0, frozen_sources=hashes([OUT/'source-hashes.json'])))
    frames, hypotheses, templates = [], [], []
    cache_counts = Counter()
    for identity in read(OUT/'identities.json'):
        sid = identity['sample_index']
        row = read(E1/'frames'/f'{sid:03d}.json')
        assert row['sample_index'] == sid
        coarse_geometry = {c['uid']:c['expanded_box'] for c in read(E0/'frames'/f'{sid:03d}.json')['entries']['A']['candidates']}
        frame_results = []
        has_template = False
        with np.load(E1/'crops'/f'{sid:03d}.npz', allow_pickle=False) as cache:
            for coarse in row['refinements']:
                key = f"coarse_{coarse['uid']}"
                if key not in cache:
                    assert not coarse['refinements']
                    continue
                original = cache[key]
                assert array_hash(original) == coarse['original_crop_sha256']
                cache_counts['coarse_arrays_checked'] += 1
                for j, line in enumerate(coarse['refinements']):
                    final = cache[f"refined_{coarse['uid']}_{j}"]
                    assert array_hash(final) == line['original_bgr_sha256']
                    cache_counts['final_arrays_checked'] += 1
                    clean_line = {k:line[k] for k in ['points_q16','observed_groups','source_polarities']}
                    result = check(original, final, clean_line, coarse['polarities'], coarse_geometry[coarse['uid']][:2])
                    record = dict(sample_index=sid, coarse_uid=coarse['uid'], local_index=j,
                        points_q16=line['points_q16'], original_e1_structural_valid=line['valid'], result=result)
                    hypotheses.append(record)
                    frame_results.append(record)
                    if len(templates) < 8 and not has_template:
                        mask = STRUCTURE['otsu32'](gray_from_bgr(final))
                        _, labels, stats, _ = components(mask)
                        eligible = [(int(s[4]), k) for k,s in enumerate(stats[1:],1)
                            if s[3] >= 23 and s[2] <= 36 and s[0] > 0 and s[1] > 0
                            and s[0]+s[2] < 224 and s[1]+s[3] < 64]
                        if eligible:
                            _, label = max(eligible)
                            x,y,w,h,_ = map(int, stats[label])
                            templates.append((sid, labels[y:y+h,x:x+w] == label))
                            has_template = True
        selection = row['selection']
        picked = None if selection['selected_index'] is None else selection['hypotheses'][selection['selected_index']]
        matching = [] if picked is None else [r for r in frame_results if r['points_q16'] == picked['points_q16']]
        if picked is not None: assert matching
        rejected = any(r['result']['reject'] for r in matching)
        status = ('new_reject' if rejected else 'retained_unknown') if picked is not None else selection['status']
        # Old evaluation fields are consulted only after the evidence decision above.
        frames.append(dict(sample_index=sid, original_status=selection['status'], status=status,
            old_correct=row['old_correct'], upstream_missing=row['upstream_missing'],
            original_iou=None if picked is None else picked['evaluation']['iou'],
            original_gt_full_containment=None if picked is None else picked['evaluation']['gt_full_containment'],
            manual_clipping=True if sid == 164 else None, complete_certified=False,
            original_hypothesis_count=len(frame_results),
            surviving_structural_hypotheses=sum(r['original_e1_structural_valid'] and not r['result']['reject'] for r in frame_results)))
    assert dict(cache_counts) == dict(coarse_arrays_checked=373, final_arrays_checked=157)
    assert len(frames) == 304 and len(hypotheses) == 157 and len(templates) == 8
    synthetic = controls(templates)
    groups = {}
    for name, group in [('all304', frames), ('old251', [f for f in frames if f['old_correct']]),
                        ('upstream_missing64', [f for f in frames if f['upstream_missing']])]:
        groups[name] = dict(counts=dict(Counter(f['status'] for f in group)),
            new_reject_ids=[f['sample_index'] for f in group if f['status'] == 'new_reject'],
            retained_unknown_ids=[f['sample_index'] for f in group if f['status'] == 'retained_unknown'])
    summary = dict(groups=groups, cache_counts=dict(cache_counts),
        hypothesis_status=dict(Counter(r['result']['status'] for r in hypotheses)),
        synthetic=dict(cases=len(synthetic), failures=[{k:r[k] for k in ['template_sample','polarity','case','known_cut','reject']}
            for r in synthetic if not r['expected_behavior_met']],
            by_case={c:dict(total=sum(r['case']==c for r in synthetic), rejected=sum(r['case']==c and r['reject'] for r in synthetic)) for c in CONTRACT['synthetic_cases']}),
        ambiguity_stays_rejected=sum(f['original_status']=='ambiguity' and f['status']=='ambiguity' for f in frames),
        ambiguity_with_one_survivor_not_promoted=[f['sample_index'] for f in frames if f['original_status']=='ambiguity' and f['surviving_structural_hypotheses']==1],
        original_source_image_reads=0, localization_calls=0, model_forwards=0, complete_certified_count=0)
    write_new(OUT/'hypotheses.json', hypotheses)
    write_new(OUT/'frames.json', frames)
    write_new(OUT/'synthetic-controls.json', synthetic)
    write_new(OUT/'summary.json', summary)
    verify_hashes(read(E1/'delivery-freeze.json')['artifacts'])
    verify_hashes(read(E0/'delivery-freeze.json')['artifacts'])
    print(summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare','run'])
    args = parser.parse_args()
    (prepare if args.action == 'prepare' else run)()
