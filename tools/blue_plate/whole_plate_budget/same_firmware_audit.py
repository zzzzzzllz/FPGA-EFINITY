"""Audit existing reports for the full edge demonstration plus OCR route; no builds."""
from pathlib import Path
import csv
import hashlib
import json
import math
import re

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / 'docs/validation/blue-plate/whole-plate-budget'
OUT = ROOT / 'tmp/blue-plate-whole-plate-budget/same-firmware'
sources = {}


def read(path):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    data = path.read_bytes()
    sources[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return data


def js(path):
    return json.loads(read(path))


def mapped(path):
    section = read(path).decode().split('Resource Summary (begin)', 1)[1].split('Resource Summary (end)', 1)[0]
    primitives = {k: int(v) for k, v in re.findall(r'^(EFX_\w+)\s*:\s*(\d+)', section, re.M)}
    assert primitives
    return dict(path=str(path), primitives=primitives,
                RAM=sum(primitives.get(k, 0) for k in ('EFX_RAM10', 'EFX_DPRAM10')),
                DSP=sum(primitives.get(k, 0) for k in ('EFX_DSP48', 'EFX_DSP24', 'EFX_DSP12')))


def placed(path):
    data = read(path).decode()
    return {name: int(re.search(r'^' + label + r':\s*(\d+) /', data, re.M)[1])
            for name, label in [('XLR', 'XLRs'), ('RAM', 'Memory Blocks'), ('DSP', 'DSP Blocks')]}


def hierarchy(path):
    rows = {}
    stack = []
    for line in read(path).decode().splitlines():
        cells = line.split('|')
        if len(cells) < 5 or '+' not in cells[1]:
            continue
        depth = cells[1].index('+') - 1
        name = cells[1].strip()[1:]
        stack = stack[:depth]
        stack.append(name)
        values = [re.fullmatch(r'\s*([\d.]+)\(([\d.]+)\)\s*', c) for c in cells[2:5]]
        assert all(values), line
        rows['/'.join(stack)] = dict(depth=depth, **{k: float(v[1]) for k, v in zip(('XLR', 'RAM', 'DSP'), values)},
                                      self_resources={k: float(v[2]) for k, v in zip(('XLR', 'RAM', 'DSP'), values)})
    assert rows
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    identity = js(DOC / 'same-firmware-release-evidence.json')
    for path, expected in identity['source_sha256'].items():
        assert hashlib.sha256(read(path)).hexdigest() == expected, path
    freeze_counts = {}
    for name in ('requant-static', 'scalar-read'):
        freeze = js(f'tmp/blue-plate-whole-plate-budget/{name}/delivery-freeze.json')
        for path, expected in freeze['files_sha256'].items():
            assert hashlib.sha256(read(path)).hexdigest() == expected, path
        freeze_counts[name] = len(freeze['files_sha256'])

    report_paths = {'full': 'tmp/build/task8-keys-20261017-v5/outflow/ti60f225_oob.',
                    'gates': 'docs/validation/blue-plate/video-base/evidence/gates-',
                    'live': 'docs/validation/blue-plate/video-base/evidence/live-'}
    builds = {name: dict(place=placed(prefix + 'place.rpt'), map=mapped(prefix + 'map.rpt'),
                        hierarchy=hierarchy(prefix + 'hier_util.rpt')) for name, prefix in report_paths.items()}
    for b in builds.values():
        root = b['hierarchy']['ti60f225_oob_top']
        assert all(root[k] == b['place'][k] for k in ('XLR', 'RAM', 'DSP'))
        assert b['map']['RAM'] == b['place']['RAM'] and b['map']['DSP'] == b['place']['DSP']
        children = [r for r in b['hierarchy'].values() if r['depth'] == 1]
        assert all(sum(r[k] for r in children) + root['self_resources'][k] == root[k] for k in ('XLR', 'RAM', 'DSP'))
    deltas = {f'{a}_minus_{b}': {k: builds[a]['place'][k] - builds[b]['place'][k] for k in ('XLR', 'RAM', 'DSP')}
              for a, b in [('full', 'gates'), ('gates', 'live'), ('full', 'live')]}
    restoration = []
    names = sorted(set().union(*(b['hierarchy'] for b in builds.values())))
    for path in names:
        depth = next(b['hierarchy'][path]['depth'] for b in builds.values() if path in b['hierarchy'])
        row = {'instance': path, 'depth': depth}
        for name, b in builds.items():
            for resource in ('XLR', 'RAM', 'DSP'):
                row[f'{name}_{resource}'] = b['hierarchy'][path][resource] if path in b['hierarchy'] else 0
        for resource in ('XLR', 'RAM', 'DSP'):
            row[f'full_minus_live_{resource}'] = row[f'full_{resource}'] - row[f'live_{resource}']
        restoration.append(row)
    with (DOC / 'same-firmware-restoration.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(restoration[0])); writer.writeheader(); writer.writerows(restoration)

    maps = {name: mapped(path) for name, path in {
        'reader': 'docs/validation/blue-plate/frame-reader/evidence/frame_reader.map.rpt',
        'geometry_color': 'tmp/blue-plate-geometry/color-output/synthesis/out/perspective_quad.map.rpt',
        'resize': 'tmp/blue-plate-ocr-input/synthesis/out/ocr_resize_q8.map.rpt',
        'writer': 'tmp/blue-plate-ocr-writer/synthesis/out/ocr_hwc_writer.map.rpt',
        'core': 'tmp/blue-plate-whole-plate-budget/scalar-read/synthesis/out/q31_scalar_mac8.map.rpt',
        'display': 'docs/validation/blue-plate/plate-display/plate_display.map.rpt'}.items()}
    base = builds['full']['place']
    limits = identity['limits']
    direct = {}
    for name, components in [('core_only', ['core']), ('input_and_core', ['reader', 'geometry_color', 'resize', 'writer', 'core']),
                             ('all_existing_modules', list(maps))]:
        direct[name] = {k: base[k] + sum(maps[c][k] for c in components) for k in ('RAM', 'DSP')}
        direct[name]['RAM_deficit'] = direct[name]['RAM'] - limits['RAM']
    full = js(DOC / 'full-lprnet-sharing.json')
    direct['planned_full_OCR'] = {'RAM': base['RAM'] + maps['reader']['RAM'] + maps['geometry_color']['RAM'] + maps['display']['RAM'] + full['memory']['shared_RAM'],
                                  'scope': 'Allocation only: replace core+resize by the 51-bank OCR plan; no external gray buffer.'}
    direct['planned_full_OCR']['RAM_deficit'] = direct['planned_full_OCR']['RAM'] - limits['RAM']
    assert [direct[n]['RAM'] for n in direct] == [206, 216, 232, 264]
    assert direct['all_existing_modules']['DSP'] == 123

    scalar = js(DOC / 'scalar-read-validation.json')['service']
    service = js(DOC / 'service-cost.json')
    config = js('tmp/blue-plate-char-segment/quantization-tap2-fork/integer-config.json')
    weights = parameters = 0
    for stage in config['stages']:
        if stage['kind'] == 'conv':
            co = stage['shape'][0]; k = stage['mac_terms']
            weights += math.ceil(co / 8) * sum(math.ceil(min(2048, k-i)*8/16)*16 for i in range(0, k, 2048))
            parameters += math.ceil(co*9/16)*16
    parameters += js(DOC / 'quantization-fork-budget.json')['parameters']['new_reserved_bytes']
    assert weights == 458784 and parameters == 14784
    arena_parts = dict(feature_slots=sum(s['capacity'] for s in full['memory']['feature_slots']),
                       padded_weights=weights, parameters=parameters, context_A8=service['memory']['context_A8_bytes'])
    known_arena = sum(arena_parts.values())
    assert known_arena == 1035040
    raw_bytes = 1280*720*3
    video = dict(capture=raw_bytes*30, algorithm_read=raw_bytes*30, result_write=1280*720*4*30,
                 display_read=1280*720*4*60)
    canny_fixed = dict(state_write=1280*720//4*30, seed_scan=1280*720//4*30, display_state=1280*720//4*60)
    cycles = scalar['new_lpr_core_cycles']
    traffic = service['traffic']['lpr']
    assert traffic['all_scalar_input_miss_payload'] == (traffic['mac_input_word_requests'] + traffic['maxpool_scalar_reads'] + traffic['context_scalar_reads'])*16 + traffic['contiguous_feature_writes'] + traffic['weight_reads'] + traffic['parameter_ddr_reads']

    source_files = ['ti60f225_oob_top.v', 'edge_algorithm_pair.v', 'rgb_to_gray.v', 'sobel_pair.v',
                    'frame_store.v', 'frame_store_control.v', 'frame_store_dma.v', 'canny_hysteresis.v', 'shape_recognizer.v']
    for file in source_files:
        read('coding/edge-quality-30fps/rtl/' + file)
    for path in ['tools/blue_plate/ocr_input/rtl/geometry_ocr_input.v', 'tools/blue_plate/geometry/rtl/perspective_quad.v',
                 'docs/validation/blue-plate/plate-display/handoff.md', 'docs/validation/blue-plate/video-base/evidence/live-candidate.diff']:
        read(path)
    original = js('docs/validation/blue-plate/video-base/evidence/live-inputs.json')['source_sha256']
    source_match = {f: hashlib.sha256(read('coding/edge-quality-30fps/' + f)).hexdigest() == h for f, h in original.items()}
    stale_bit = read('tmp/build/edge-quality-30fps/outflow/ti60f225_oob.bit')
    stale_hash = hashlib.sha256(stale_bit).hexdigest()
    assert stale_hash != identity['bitstream_sha256']
    result = dict(status='Read-only audit complete; full-firmware OCR integration is not mapped or accepted',
                  current_route='Full edge demonstration and OCR in one firmware; detector/color CNN and HS outside this route',
                  limits={**limits, 'private_DDR_bytes': 8*1024*1024}, release=identity,
                  stale_generic_build_bit_sha256=stale_hash, builds=builds, restoration_deltas=deltas,
                  standalone_maps=maps, direct_addition=direct, integrated_XLR=None,
                  unmapped_locator_resources=None, unmapped_control_resources=None,
                  private_arena=dict(known_components=arena_parts, known_subtotal=known_arena,
                                     with_optional_raw_copy=known_arena+raw_bytes, remaining_before_unknowns=8*1024*1024-known_arena,
                                     complete_allocation=None, historical_three_model_reservation=service['memory']['arena_bytes']),
                  service=dict(known_OCR_core_cycles=cycles, assumed_clock_Hz=100000000, known_core_ms=cycles/100000,
                               ideal_core_only_tasks_per_second=100000000/cycles,
                               remaining_source_age_ms_before_500ms=500-cycles/100000,
                               end_to_end_latency_ms=None, locator_cycles=None,
                               omitted='pool, context energy/gain, height, CTC, geometry, locator, arbitration, control and stalls'),
                  traffic=dict(OCR_payload_scenario=traffic, input_writer_bytes=6768, geometry_neighbor_requests=57344,
                               geometry_DDR_bytes=None, video_fixed_components_bytes_per_second=video,
                               video_fixed_sum=sum(video.values()), canny_fixed_additions_bytes_per_second=canny_fixed,
                               canny_fixed_sum=sum(video.values())+sum(canny_fixed.values()),
                               shape_state_copy_bytes_per_job=1280*720//4*2, total_video_bandwidth=None,
                               guaranteed_OCR_bandwidth=None, finite_WCET=None,
                               note='Payload scenarios, not measurements or bus guarantees; queue/cache/reference modes add data-dependent traffic'),
                  source_snapshot_match=source_match, frozen_file_counts=freeze_counts,
                  research=js(OUT/'research/sources.json'))
    result['source_sha256'] = sources.copy()
    result['sources_unchanged'] = all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p, h in sources.items())
    assert result['sources_unchanged']
    for directory in (DOC, OUT):
        (directory/'same-firmware-audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('direct_addition', 'private_arena', 'service', 'frozen_file_counts', 'sources_unchanged')}, indent=2))
    print('Original live source snapshot matches:', sum(source_match.values()), '/', len(source_match))


if __name__ == '__main__':
    main()
