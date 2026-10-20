"""Read-only single ablation: remove native color CNN, preserve HS/boundaries.

Uses saved development decisions only. No images, model execution, or tuning.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from ctc_interval import rank_candidates

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT/'tmp/blue-plate-char-segment'
DETECTOR = ROOT/'tmp/blue-plate-normal-g1/mature-detector'
OUT = DATA/'color-cnn-ablation'
READS = {}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    READS[path.relative_to(ROOT).as_posix()] = sha(path)
    return json.loads(path.read_text(encoding='utf-8'))


def write(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def state(row):
    if not row['legal']:
        return 'grammar_reject'
    lo, hi = row['probability_lower_q30'], row['probability_upper_q30']
    return 'accept' if lo >= 1023453813 else 'reject' if hi < 1023453813 else 'undecided'


def choose(rows, gate):
    eligible = [r for r in rows if r['legal'] and r[gate]]
    rank = rank_candidates([dict(roi_index=r['roi_index'], bounds=r['bounds_q30']) for r in eligible])
    winner = next((r for r in eligible if r['roi_index'] == rank['selected_roi_index']), None)
    status = 'reject' if rank['status'] == 'no_candidate' else 'undecided' if rank['status'] == 'undecided' else winner['ocr_status']
    code = winner['code'] if status == 'accept' else None
    outcome = 'undecided' if status == 'undecided' else 'rejected' if code is None else 'correct' if code == rows[0]['label'] else 'wrong'
    return dict(ranking=rank, acceptance_status=status, code=code, outcome=outcome)


def development():
    gates = read(DATA/'pretrained-new-rois/gates.json')
    q30 = read(DATA/'ctc-q30/development-roi-intervals.json')
    predictions = read(DATA/'quantization-tap2-fork/roi-predictions.json')
    manifest = read(DATA/'experiment/dev-manifest.json')['records']
    frozen_frames = {r['sample_index']: r for r in read(DATA/'ctc-q30/development-frame-comparison.json') if r['mode'] == 'combined'}
    native = {r['sample_index']: r for r in read(DETECTOR/'fullframe-rejection/records.json')
              if r['kind'] == 'positive' and r['split'] == 'development'}
    color = {r['sample_index']: r for r in read(DETECTOR/'color-evidence-development/records.json')
             if r['kind'] == 'development_positive_frame'}
    assert len(gates) == len(q30) == len(predictions) == len(manifest) == 307
    assert len(native) == len(color) == len(frozen_frames) == 304
    rows, groups = [], defaultdict(list)
    for i, (g, q, prediction, source) in enumerate(zip(gates, q30, predictions, manifest)):
        assert g['roi_index'] == q['roi_index'] == prediction['roi_index'] == source['roi_index'] == i
        assert g['sample_index'] == q['sample_index'] == source['sample_index']
        assert source['original_split'] == 'development' and source['split'] in ('train', 'tune')
        frame = native[g['sample_index']]
        p = frame['outputs'][g['candidate_index']]
        c = color[g['sample_index']]['outputs'][g['candidate_index']]
        assert frame['source'] == source['path']
        assert p['points'] == source['points'] == source['teacher_cached']['points']
        assert p['box'] == source['teacher_cached']['box']
        assert p['code'] == c['code'] == source['teacher_cached']['code']
        assert abs(p['confidence']-c['confidence']) < 1e-12
        assert q['code'] == prediction['code'] and q['decoded_ids'] == prediction['decoded_ids'] and q['legal'] == prediction['legal']
        assert q['label'] == source['source_transcript'] == frame['original_reference_text']
        hs = c['color_evidence']['counts']['blue_hs'] > c['color_evidence']['counts']['yellow_hs']
        boundary = p['corner_margin'] >= 1 and p['box_margin'] >= 1
        cnn = p['color_class'] == 0
        assert g['blue_count'] == c['color_evidence']['counts']['blue_hs'] and g['yellow_count'] == c['color_evidence']['counts']['yellow_hs']
        assert g['hs_blue_over_yellow'] == hs and g['color_class'] == p['color_class']
        assert g['corner_margin'] == p['corner_margin'] and g['box_margin'] == p['box_margin']
        assert g['combined_pass'] == q['combined_pass'] == (hs and boundary and cnn)
        assert state(q) == q['acceptance_status']
        before, after = hs and boundary and cnn, hs and boundary
        row = dict(**g, label=q['label'], split=source['split'], source=source['path'], source_sha256=source['source_sha256'],
            code=q['code'], legal=q['legal'], decoded_ids=q['decoded_ids'], bounds_q30=[q['probability_lower_q30'],q['probability_upper_q30']],
            frozen_float_score=prediction['score'], ocr_status=state(q), cnn_pass=cnn, boundary_pass=boundary,
            without_cnn_pass=after, baseline_accept=before and state(q)=='accept', ablated_accept=after and state(q)=='accept',
            exclusive_cnn_rejection=after and not cnn, points=p['points'], box=p['box'])
        rows.append(row)
        groups[g['sample_index']].append(row)
    frames = []
    for sample, group in groups.items():
        baseline, ablated = choose(group, 'combined_pass'), choose(group, 'without_cnn_pass')
        old = frozen_frames[sample]
        for key in ('ranking', 'acceptance_status', 'code', 'outcome'):
            assert baseline[key] == old[key], (sample, key)
        frames.append(dict(sample_index=sample, label=group[0]['label'], split=group[0]['split'],
            roi_indices=[r['roi_index'] for r in group], baseline=baseline, without_cnn=ablated,
            selection_changed=baseline['ranking'] != ablated['ranking'], acceptance_changed=baseline['code'] != ablated['code']))
    changes = dict(gate_changes=[r for r in rows if r['combined_pass'] != r['without_cnn_pass']],
        new_roi_accepts=[r for r in rows if r['ablated_accept'] and not r['baseline_accept']],
        lost_roi_accepts=[r for r in rows if r['baseline_accept'] and not r['ablated_accept']],
        frame_changes=[r for r in frames if r['baseline'] != r['without_cnn']],
        baseline_wrong=[r for r in frames if r['baseline']['outcome']=='wrong'],
        ablated_wrong=[r for r in frames if r['without_cnn']['outcome']=='wrong'],
        cnn_nonblue=[r for r in rows if not r['cnn_pass']])
    counts = {mode: dict(Counter(r[mode]['outcome'] for r in frames)) for mode in ('baseline','without_cnn')}
    gates_count = {key: sum(bool(r[key]) for r in rows) for key in ('cnn_pass','hs_blue_over_yellow','boundary_pass','combined_pass','without_cnn_pass')}
    write('development-rois.json', rows)
    write('development-frames.json', frames)
    write('development-changes.json', changes)
    return dict(rois=len(rows), frames=len(frames), gates=gates_count, counts=counts,
                exact_frozen_frame_replay=True, gate_changes=len(changes['gate_changes']),
                frame_changes=len(changes['frame_changes']), new_roi_accepts=len(changes['new_roi_accepts']),
                lost_roi_accepts=len(changes['lost_roi_accepts'])), rows


def negatives(dev_rows):
    # Shared JSON containers also have validation entries. Filter on split before
    # consulting any proposal, color, label or OCR field from those entries.
    frames = [r for r in read(DETECTOR/'lpr-rejection/records.json') if r['split'] in ('development','seen_real_diagnostic')]
    counts, records, frame_records = defaultdict(Counter), [], []
    dev_samples = {r['sample_index'] for r in dev_rows}
    for f in frames:
        assert f['expected_output'] == 'reject'
        if f['split'] == 'development':
            assert f['sample_index'] in dev_samples
        tally = counts[f['kind']]
        tally['inputs'] += 1
        candidates = []
        for p in f['outputs']:
            tally['proposals'] += 1
            identity = dict(id=f['id'], kind=f['kind'], input_kind=f['input_kind'], split=f['split'],
                source=f['path'], expected_output='reject', manual_label=f.get('manual_label'),
                review_note=f.get('review_note'), candidate_index=p['candidate_index'])
            if 'native_color' not in p:
                assert p['skip_reason'] == 'double_line'
                records.append(dict(**identity, skipped='double_line'))
                tally['skipped_double_line'] += 1
                continue
            c = p['native_color']
            hs, cnn, boundary = c['blue_count'] > c['yellow_count'], c['color_class']==0, p['boundary_pass']
            assert hs == c['hs_pass']
            assert c['color_class'] == max(range(3), key=lambda j:c['scores'][j])
            if f['input_kind'] == 'frame':
                assert boundary == (p['corner_margin'] >= 1 and p['box_margin'] >= 1)
            else:
                assert boundary is None
            # None retains the missing frame boundary; it is never silently True.
            after = False if not hs or boundary is False else None if boundary is None else True
            before = False if not cnn else after
            old = p['ocr']
            assert old['strict_accepts'] == (old['legal'] and old['score'] >= 0.9931710550839266)
            historical_eligible = old['strict_accepts'] and hs and cnn and boundary is not False
            row = dict(**identity, roi_index=p['roi_index'], native_color=c, boundary_pass=boundary,
                corner_margin=p.get('corner_margin'), box_margin=p.get('box_margin'), bgr_sha256=p['bgr_sha256'],
                baseline_gate=before, without_cnn_gate=after, color_only_exclusive=hs and not cnn,
                full_gate_exclusive=after is True and before is False,
                historical_fp32_ocr=old, historical_native_combined_accept=historical_eligible,
                current_integer_ocr_available=False, current_integer_acceptance=None)
            records.append(row)
            candidates.append((p, historical_eligible))
            tally.update(dict(scored_rois=1, hs_pass=int(hs), cnn_blue=int(cnn), boundary_missing=int(boundary is None),
                full_without_cnn_pass=int(after is True), full_baseline_pass=int(before is True),
                color_only_exclusive=int(hs and not cnn), full_gate_exclusive=int(after is True and before is False)))
        eligible = [p for p, yes in candidates if yes]
        selected = max(eligible, key=lambda p:(p['ocr']['score'], -p['candidate_index']), default=None)
        selection = None if selected is None else dict(candidate_index=selected['candidate_index'],roi_index=selected['roi_index'],code=selected['ocr']['code'],score=selected['ocr']['score'])
        assert selection == f['selections']['strict/native_cnn_native']
        tally['historical_fp32_native_accepts'] += int(selected is not None)
        frame_records.append(dict(id=f['id'],kind=f['kind'],input_kind=f['input_kind'],
            expected_output='reject', historical_fp32_native_selection=selection,
            current_integer_false_acceptance=None, current_integer_ocr_available=False))
    write('negative-gates.json', records)
    write('negative-historical-frames.json', frame_records)
    write('negative-exclusive-cases.json', [r for r in records if r.get('color_only_exclusive')])

    color = [r for r in read(DETECTOR/'color-evidence-development/records.json') if r['kind'].startswith('synthetic_')]
    probes = {(r['sample_index'],r['kind']):r for r in read(DETECTOR/'rejection-probe/records.json')
              if r.get('source_split')=='development' and r['kind'] in ('green_recolor','yellow_recolor')}
    synthetics, synthetic_counts = [], defaultdict(Counter)
    max_mean_delta = 0.
    for f in color:
        kind = {'synthetic_green_patch':'green_recolor','synthetic_yellow_patch':'yellow_recolor'}[f['kind']]
        p = probes[f['sample_index'],kind]
        ev = f['outputs'][0]['color_evidence']
        assert f['sample_index'] in dev_samples
        sources = [r for r in dev_rows if r['sample_index']==f['sample_index']]
        assert all(r['source'] == p['source'] for r in sources)
        assert f['outputs'][0]['code'] == p['code']
        assert ev['counts']['blue_hs']/ev['area'] == p['hs_coverage']
        delta = abs(f['outputs'][0]['confidence']-p['confidence'])
        assert delta < 2e-7
        max_mean_delta = max(max_mean_delta,delta)
        hs = ev['counts']['blue_hs'] > ev['counts']['yellow_hs']
        assert hs == ev['hs_blue_over_yellow']
        cnn = p['color_class']==0
        assert p['color_class'] == max(range(3), key=lambda j:p['color_scores'][j])
        row = dict(sample_index=f['sample_index'],kind=kind,source=p['source'],original_transcript=p['label'],
            expected_output='reject_as_nonblue_synthetic_patch', blue_count=ev['counts']['blue_hs'],
            yellow_count=ev['counts']['yellow_hs'], area=ev['area'], hs_pass=hs,
            color_class=p['color_class'], color_scores=p['color_scores'], cnn_blue=cnn,
            color_only_exclusive=hs and not cnn, boundary_pass=None,
            original_frame_boundary_pass=all(r['boundary_pass'] for r in sources),
            historical_hyperlpr_code=p['code'],historical_hyperlpr_mean=p['confidence'],
            current_integer_acceptance=None, current_integer_ocr_available=False,
            association='same development ID/source and generator anchor/recolor path; exact blue_count/area; same old OCR string, mean within 2e-7; no edited-pixel hash stored')
        synthetics.append(row)
        synthetic_counts[kind].update(dict(inputs=1,hs_pass=int(hs),cnn_blue=int(cnn),color_only_exclusive=int(hs and not cnn)))
    assert len(synthetics)==608
    write('synthetic-color-records.json',synthetics)
    write('synthetic-color-exclusive-cases.json',[r for r in synthetics if r['color_only_exclusive']])
    return dict(inputs=len(frames), by_kind=dict(counts), current_integer_false_accepts=None,
        current_integer_negative_results_available=False, synthetic_by_kind=dict(synthetic_counts),
        synthetic_associations=len(synthetics), max_historical_mean_delta=max_mean_delta,
        synthetic_current_integer_false_accepts=None,
        gaps=['All 1022 scored diagnostic ROIs have historical FP32 LPRNet OCR, not frozen fork W8/A8+Q30.',
              '96 real patches have boundary_pass=null; historical code allowed null only for downstream diagnostics.',
              '608 recolored patches lack current integer OCR and edited full-frame detection/boundary records.',
              'Other historical patch-removal/background probes lack paired yellow HS counts and frame boundary fields; no full gate comparison claimed.',
              'No validation84 or heldout112 is used for comparisons or decisions. No image arrays or models loaded.'])


def main():
    if OUT.exists():
        raise FileExistsError(OUT)
    OUT.mkdir(parents=True)
    dev, rows = development()
    neg = negatives(rows)
    sources = [Path(__file__), Path(__file__).with_name('ctc_interval.py'),
        Path(__file__).with_name('pretrained_new_rois.py'),Path(__file__).with_name('verify_ctc_q30.py'),
        Path(__file__).with_name('fixed_lprnet.py')]
    sources += [ROOT/'tools/blue_plate'/p for p in ['probe_hyperlpr_fullframe.py','diagnose_color_evidence.py',
        'probe_hyperlpr_rejection.py','hyperlpr_reference.py','prepare_lpr_rejection.py','evaluate_lpr_rejection.py']]
    upstream = ROOT/'tmp/blue-plate-review/mature-research/hyperlpr'
    sources += [upstream/'Prj-Python/hyperlpr3'/p for p in ['inference/classification.py','inference/pipeline.py','common/typedef.py']]
    pinned = read(upstream/'manifest.json')
    for p in sources:
        READS[p.relative_to(ROOT).as_posix()] = sha(p)
        if p.is_relative_to(upstream):
            item=next(r for r in pinned['files'] if r['path']==p.relative_to(upstream).as_posix())
            assert sha(p)==item['sha256']
    summary=dict(development=dev,negative_diagnostics=neg,network_inferences=0,training_steps=0,
        source_image_reads=0,input_array_reads=0,threshold_changes=0,production_gate_changes=0,
        decision='No replacement approval. Zero development effect; six paired synthetic color-only exclusions; current integer negative false-accept rate remains unmeasured.',
        source_research=dict(repo=pinned['repo'],commit=pinned['commit'],
            actual_files_read=['inference/classification.py','inference/pipeline.py','common/typedef.py'],
            implementation='Native BGR crop -> resize96x96 -> /255 float32 CHW -> three-class model -> argmax, blue0 green1 yellow2; frozen custom gate always evaluates CNN independently of current OCR.'))
    assert all(sha(ROOT/p)==h for p,h in READS.items())
    write('summary.json',summary)
    write('source-freeze.json',dict(source_hashes=READS,scope='development307 + existing development/seen-real diagnostic metadata; shared containers filtered before analysis'))
    print(json.dumps(summary,ensure_ascii=True))


if __name__=='__main__':
    main()
