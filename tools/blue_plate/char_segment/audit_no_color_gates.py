"""Replay frozen development logits without CNN/HS gates; zero model forwards."""
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from ctc_interval import collapse, emissions, ctc_bounds, rank_candidates

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'tmp/blue-plate-char-segment'
OUT = BASE / 'no-color-gates'
THRESHOLD = 1023453813
SOURCES = {}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def track(path):
    SOURCES[path.relative_to(ROOT).as_posix()] = sha(path)
    return path


def read(path):
    return json.loads(track(path).read_text(encoding='utf-8'))


def write(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def grammar_function():
    source = ROOT / 'tools/blue_plate/baseline.py'
    tree = ast.parse(track(source).read_text(encoding='utf-8'))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('PROVINCES', 'LETTERS'):
                constants[name] = ast.literal_eval(node.value)
            elif name == 'ADS':
                assert isinstance(node.value, ast.BinOp) and node.value.left.id == 'LETTERS'
                constants[name] = constants['LETTERS'] + ast.literal_eval(node.value.right)
    source = ROOT / 'tools/blue_plate/compare_hyperlpr.py'
    tree = ast.parse(track(source).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'grammar')
    scope = dict(b=SimpleNamespace(**constants))
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
    return scope['grammar']


def choose(rows, mode):
    eligible = [r for r in rows if r['legal'] and r[mode + '_gate']]
    rank = rank_candidates([dict(roi_index=r['roi_index'], bounds=r['bounds_q30'], signature=r['_signature']) for r in eligible])
    winner = next((r for r in eligible if r['roi_index'] == rank['selected_roi_index']), None)
    status = 'reject' if rank['status'] == 'no_candidate' else 'undecided' if rank['status'] == 'undecided' else winner['ocr_status']
    code = winner['code'] if status == 'accept' else None
    outcome = 'undecided' if status == 'undecided' else 'rejected' if code is None else 'correct' if code == rows[0]['label'] else 'wrong'
    return dict(ranking=rank, acceptance_status=status, code=code, outcome=outcome)


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    grammar = grammar_function()
    manifest = read(BASE / 'experiment/dev-manifest.json')['records']
    gates = read(BASE / 'pretrained-new-rois/gates.json')
    q30 = read(BASE / 'ctc-q30/development-roi-intervals.json')
    frames_old = {r['sample_index']: r for r in read(BASE / 'ctc-q30/development-frame-comparison.json') if r['mode'] == 'combined'}
    logits = np.load(track(BASE / 'quantization-tap2-fork/integer-logits.npz'), allow_pickle=False)['logits']
    assert logits.shape == (307, 68, 18) and logits.dtype == np.int16
    assert len(manifest) == len(gates) == len(q30) == 307
    alphabet_path = ROOT / 'tmp/blue-plate-review/mature-research/lprnet/data/load_data.py'
    tree = ast.parse(track(alphabet_path).read_text(encoding='utf-8'))
    chars = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                and any(isinstance(t, ast.Name) and t.id == 'CHARS' for t in n.targets)))
    lut = read(BASE / 'ctc-q30/lut.json')
    table = [(v, v if i == 0 else v + 1) for i, v in enumerate(lut['lower'])]
    table += [(0, 1)] * (1021 - len(table))
    rows, groups = [], defaultdict(list)
    for i, (m, g, q, x) in enumerate(zip(manifest, gates, q30, logits)):
        assert m['roi_index'] == g['roi_index'] == q['roi_index'] == i
        assert m['sample_index'] == g['sample_index'] == q['sample_index']
        assert m['original_split'] == 'development' and m['split'] in ('train', 'tune')
        target = collapse(x.argmax(axis=0).tolist(), 67)
        code = ''.join(chars[c] for c in target)
        legal = bool(grammar(code))
        assert target == q['decoded_ids'] and code == q['code'] and legal == q['legal']
        distances = (x.max(axis=0).astype(np.int32)[None] - x.astype(np.int32)).T
        bounds = ctc_bounds(emissions(distances, table, 30), target, 30)
        assert list(bounds) == [q['probability_lower_q30'], q['probability_upper_q30']]
        status = 'grammar_reject' if not legal else 'accept' if bounds[0] >= THRESHOLD else 'reject' if bounds[1] < THRESHOLD else 'undecided'
        assert status == q['acceptance_status']
        boundary = g['corner_margin'] >= 1 and g['box_margin'] >= 1
        old_gate = g['color_class'] == 0 and g['hs_blue_over_yellow'] and boundary
        assert old_gate == g['combined_pass'] == q['combined_pass']
        row = dict(roi_index=i, sample_index=m['sample_index'], candidate_index=g['candidate_index'],
                   split=m['split'], original_split=m['original_split'], source=m['path'], source_sha256=m['source_sha256'],
                   label=q['label'], code=code, legal=legal, decoded_length=len(target), decoded_ids=target,
                   bounds_q30=list(bounds), ocr_status=status, boundary_pass=boundary,
                   corner_margin=g['corner_margin'], box_margin=g['box_margin'],
                   old_cnn_pass=g['color_class'] == 0, old_hs_pass=g['hs_blue_over_yellow'],
                   baseline_gate=old_gate, no_color_gate=boundary,
                   baseline_accept=old_gate and status == 'accept', no_color_accept=boundary and status == 'accept',
                   _signature=(x.tobytes(), tuple(target)))
        assert row['label'] == m['source_transcript']
        for mode in ('baseline', 'no_color'):
            row[mode + '_outcome'] = 'correct' if row[mode + '_accept'] and code == row['label'] else 'wrong' if row[mode + '_accept'] else 'undecided' if row[mode + '_gate'] and status == 'undecided' else 'rejected'
        rows.append(row)
        groups[row['sample_index']].append(row)
    assert len(groups) == len(frames_old) == 304
    frames = []
    for sample, group in groups.items():
        before, after = choose(group, 'baseline'), choose(group, 'no_color')
        for key in before:
            assert before[key] == frames_old[sample][key], (sample, key)
        frames.append(dict(sample_index=sample, label=group[0]['label'], split=group[0]['split'],
                           roi_indices=[r['roi_index'] for r in group], baseline=before, no_color=after,
                           selection_changed=before['ranking'] != after['ranking'],
                           output_changed=(before['acceptance_status'], before['code']) != (after['acceptance_status'], after['code'])))
    for row in rows:
        del row['_signature']
    changes = dict(gate_changes=[r for r in rows if r['baseline_gate'] != r['no_color_gate']],
                   new_roi_accepts=[r for r in rows if r['no_color_accept'] and not r['baseline_accept']],
                   lost_roi_accepts=[r for r in rows if r['baseline_accept'] and not r['no_color_accept']],
                   frame_changes=[r for r in frames if r['baseline'] != r['no_color']],
                   new_frame_accepts=[r for r in frames if r['baseline']['code'] is None and r['no_color']['code'] is not None],
                   new_frame_errors=[r for r in frames if r['no_color']['outcome'] == 'wrong' and r['baseline']['outcome'] != 'wrong'],
                   new_frame_rejections=[r for r in frames if r['no_color']['outcome'] == 'rejected' and r['baseline']['outcome'] != 'rejected'],
                   all_remaining_frame_errors=[r for r in frames if r['no_color']['outcome'] == 'wrong'],
                   all_remaining_frame_rejections=[r for r in frames if r['no_color']['outcome'] == 'rejected'])
    summary = dict(rois=307, frames=304, q30_recomputed_exactly=307, frozen_baseline_replayed_exactly=304,
                   gates_before=sum(r['baseline_gate'] for r in rows), gates_after=sum(r['no_color_gate'] for r in rows),
                   roi_counts={m:dict(Counter(r[m + '_outcome'] for r in rows)) for m in ('baseline', 'no_color')},
                   frame_counts={m:dict(Counter(r[m]['outcome'] for r in frames)) for m in ('baseline', 'no_color')},
                   changes={k:len(v) for k,v in changes.items()}, image_reads=0, model_forwards=0,
                   policy='Keep exact 7-character grammar, frozen Q30 threshold/ranking, corner_margin>=1 and box_margin>=1; remove CNN and HS gates',
                   scope='Frozen 307 development proposals only; no new localization; recolored images are outside this replay and nonblue alone is not an error')
    OUT.mkdir()
    write('roi-records.json', rows)
    write('frame-records.json', frames)
    write('changes.json', changes)
    write('summary.json', summary)
    track(Path(__file__))
    track(Path(__file__).with_name('ctc_interval.py'))
    write('source-hashes.json', SOURCES)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(changes['new_frame_accepts'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
