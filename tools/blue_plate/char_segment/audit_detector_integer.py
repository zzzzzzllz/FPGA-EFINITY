"""Static detector contract audit. No image reads, inference, or parameter export."""
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'tmp/blue-plate-char-segment'
RESEARCH = DATA / 'detector-integer-research'
sys.path.insert(0, str(RESEARCH / 'python'))
import numpy as np
import onnx

MODEL = ROOT / 'tmp/blue-plate-normal-g1/mature-detector/y5fu_320x_sim.onnx'
OUT = DATA / 'detector-integer-audit'
EXPECTED_SHA = '2a985dc63a5cc947ec36d18503d6fc0fd54525b9dba17f2fe29a71e86b44456d'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plain(value):
    if isinstance(value, bytes):
        return value.decode('utf-8')
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def main():
    if OUT.exists():
        raise FileExistsError(f'Preserve audit: {OUT}')
    assert sha(MODEL) == EXPECTED_SHA
    model = onnx.load(str(MODEL))
    onnx.checker.check_model(model)
    graph = model.graph
    arrays = {t.name: onnx.numpy_helper.to_array(t) for t in graph.initializer}
    tensors = {}
    for t in [*graph.input, *graph.value_info, *graph.output]:
        tt = t.type.tensor_type
        tensors[t.name] = dict(dtype=onnx.TensorProto.DataType.Name(tt.elem_type),
                              shape=[d.dim_value for d in tt.shape.dim])
    for name, a in arrays.items():
        tensors[name] = dict(dtype=str(a.dtype), shape=list(a.shape), initializer=True)
    nodes = list(graph.node)
    by_output = {o: n for n in nodes for o in n.output}
    consumers = defaultdict(list)
    for n in nodes:
        for i in n.input:
            consumers[i].append(n.name)
    attrs = {n.name: {a.name: plain(onnx.helper.get_attribute_value(a)) for a in n.attribute} for n in nodes}
    heads = {'Conv_500', 'Conv_596', 'Conv_692'}
    core = nodes[:next(i for i, n in enumerate(nodes) if n.name == 'Conv_500')]
    silu = {}
    for n in core:
        if n.op_type == 'Mul':
            matches = [(i, j) for i, j in [(0, 1), (1, 0)]
                       if n.input[i] in by_output and by_output[n.input[i]].op_type == 'Sigmoid'
                       and by_output[n.input[i]].input[0] == n.input[j]]
            assert len(matches) == 1
            i, j = matches[0]
            sig = by_output[n.input[i]]
            assert consumers[sig.output[0]] == [n.name]
            silu[n.name] = dict(input=n.input[j], sigmoid=sig.name, output=n.output[0],
                               entries=256, bytes=256, indexing='unsigned reinterpretation of signed int8')
    assert len(silu) == 63 and not any(n.op_type == 'Add' for n in core)
    assert len(nodes) == 416 and len(arrays) == 235 and len(core) == 310
    assert all(tensors[t.name]['dtype'] == 'FLOAT' for t in [*graph.input, *graph.value_info, *graph.output])
    core_names = {n.name for n in core}
    scales = {'input': 'fixed_input_s=1/255,z=-128'}
    rows, convs, concats, adds = [], [], [], []
    old = read(ROOT / 'tmp/blue-plate-normal-g1/mature-detector/model-costs.json')['detector320']['layers']
    old_by_name = {r['name']: r for r in old}
    for index, n in enumerate(nodes):
        row = dict(index=index, name=n.name, op=n.op_type, attributes=attrs[n.name],
                   inputs=[dict(name=i, **tensors[i]) for i in n.input if i],
                   outputs=[dict(name=o, **tensors[o]) for o in n.output],
                   consumers={o: consumers[o] for o in n.output})
        if n.op_type == 'Conv':
            w, b = arrays[n.input[1]], arrays[n.input[2]]
            co, ci, kh, kw = w.shape
            shape = tensors[n.output[0]]['shape']
            group = attrs[n.name].get('group', 1)
            cin = tensors[n.input[0]]['shape'][1]
            depthwise = group == cin == co and ci == 1
            k, positions = ci * kh * kw, math.prod(shape[2:])
            c = dict(name=n.name, input=n.input[0], output=n.output[0], input_shape=tensors[n.input[0]]['shape'],
                     output_shape=shape, weight=n.input[1], bias=n.input[2], weight_shape=list(w.shape),
                     groups=group, depthwise=depthwise, K=k, output_elements=math.prod(shape),
                     macs=int(w.size * positions), weight_tile_bytes=int(k * 8),
                     lane_groups=math.ceil(co / 8), last_group_valid_lanes=(co - 1) % 8 + 1,
                     mac8_cycles=int(positions * (math.ceil(co / 8) * kh * kw if depthwise else math.ceil(co / 8) * k)),
                     bias_float_min=float(b.min()), bias_float_max=float(b.max()),
                     quantized_parameters_exist=False, planned_weights='symmetric int8 per output channel',
                     planned_accumulator='signed int32 after full-domain overflow proof',
                     planned_output='affine signed int8; q_relu=0', input_scale=scales[n.input[0]],
                     output_scale=f'calibrated:{n.output[0]}', metadata_channels=int(co))
            prior = old_by_name['onnx_node!' + n.name]
            assert prior['outputs'][0] == shape and prior['blobs'][0] == list(w.shape) and prior['macs'] == c['macs']
            convs.append(c)
            scales[n.output[0]] = c['output_scale']
            row['deployment'] = dict(dtype='int8', scale=scales[n.output[0]], lowering='MAC8 then Q31; no ReLU')
        elif n.name in core_names:
            if n.name in silu:
                scales[n.output[0]] = f'calibrated:{n.output[0]}'
                row['deployment'] = dict(dtype='int8', lowering='fused 256-entry SiLU table', scale=scales[n.output[0]])
            elif n.op_type == 'Sigmoid':
                scales[n.output[0]] = 'virtual:silu'
                row['deployment'] = dict(dtype='none', lowering='virtual; fused into following SiLU lookup')
            elif n.op_type == 'Concat':
                assert attrs[n.name]['axis'] == 1
                scales[n.output[0]] = f'calibrated_union:{n.output[0]}'
                c = dict(name=n.name, axis=1, inputs=[dict(tensor=i, shape=tensors[i]['shape'], scale=scales[i],
                          other_consumers=[x for x in consumers[i] if x != n.name]) for i in n.input],
                         output=n.output[0], output_shape=tensors[n.output[0]]['shape'],
                         output_scale=scales[n.output[0]], elements=math.prod(tensors[n.output[0]]['shape']),
                         policy='edge-only Q31 rescale directly into concat destination; preserve source scale for other users')
                concats.append(c)
                row['deployment'] = dict(dtype='int8', scale=scales[n.output[0]], lowering=c['policy'])
            else:
                assert n.op_type in {'Slice', 'Reshape', 'Transpose', 'Resize', 'MaxPool'}
                scales[n.output[0]] = scales[n.input[0]]
                row['deployment'] = dict(dtype='int8', scale=scales[n.output[0]],
                                         lowering='value-preserving layout/copy or max; preserve scale and zero')
        else:
            row['deployment'] = dict(dtype='virtual', lowering='fused head decode; see head-decode.json',
                                     fields='raw heads int8; probabilities uint32 Q30; coordinates int32 Q16.16')
            if n.op_type == 'Add':
                constants = [i for i in n.input if i in arrays]
                assert len(constants) == 1
                a = arrays[constants[0]]
                role = 'remove exact zero addition' if np.all(a == 0) else 'exact integer grid offset addition'
                adds.append(dict(name=n.name, constant=constants[0], role=role, residual=False))
        row['constant_inputs'] = {i: arrays[i].tolist() for i in n.input if i in arrays and arrays[i].size <= 16}
        rows.append(row)
    assert len(convs) == 85 and sum(c['depthwise'] for c in convs) == 19
    assert len(concats) == 25 and len(adds) == 18
    assert sum(c['macs'] for c in convs) == 183417600
    assert sum(c['mac8_cycles'] for c in convs) == 22977600
    head_rows = []
    for h, (conv, side, stride, anchor, grid, gridpix, zero) in enumerate([
        ('Conv_500', 40, 8, '1005', '992', '1014', '981'),
        ('Conv_596', 20, 16, '1118', '1105', '1127', '1094'),
        ('Conv_692', 10, 32, '1231', '1218', '1240', '1207')]):
        a = arrays[anchor]
        anchors = a[0, :, 0, 0, :]
        assert np.array_equal(a, np.broadcast_to(anchors[None, :, None, None, :], a.shape))
        yy, xx = np.mgrid[:side, :side]
        expected_grid = np.broadcast_to(np.stack([xx, yy], axis=-1)[None, None], arrays[grid].shape)
        assert np.array_equal(arrays[grid], expected_grid)
        assert np.array_equal(arrays[gridpix], expected_grid * stride)
        assert np.all(arrays[zero] == 0)
        head_rows.append(dict(head=h, convolution=conv, side=side, stride=stride, anchors=anchors.tolist(),
                              rows=3 * side * side, raw_shape=[1, 45, side, side],
                              tensor=by_output[next(n.output[0] for n in nodes if n.name == conv)].output[0],
                              order='scale then anchor then y then x; fields cx,cy,w,h,obj,4*(x,y),class0,class1',
                              sigmoid_fields=[0, 1, 2, 3, 4, 13, 14], linear_fields=list(range(5, 13)),
                              zero_initializer=zero, eliminated_zero_bytes=arrays[zero].nbytes,
                              proposed_tables=dict(probability=1, center_offset=1, wh=6, landmark_offset=6,
                                                   entries_each=256, bytes_each=1024, total_bytes=14336)))
    manifest_path = DATA / 'experiment/dev-manifest.json'
    calib_path = DATA / 'quantization-w8a8/parameter-freeze.json'
    manifest = read(manifest_path)['records']
    assert all(r['original_split'] == 'development' for r in manifest)
    calibration_rois = read(calib_path)['calibration_roi_indices']
    assert len(calibration_rois) == len(set(calibration_rois)) == 207
    assert all(manifest[i]['roi_index'] == i and manifest[i]['split'] == 'train' for i in calibration_rois)
    calibration_ids = {manifest[i]['sample_index'] for i in calibration_rois}
    assert len(calibration_ids) == 207
    identity = {}
    for r in manifest:
        key = r['sample_index']
        entry = {k: r[k] for k in ('sample_index', 'path', 'source_sha256', 'split', 'original_split')}
        assert key not in identity or identity[key] == entry
        identity[key] = entry
    assert len(identity) == 304
    assert Counter(r['split'] for r in identity.values()) == {'train': 228, 'tune': 76}
    plan_rows = [dict(identity[i], calibration=i in calibration_ids, fp32_passes=1, integer_passes=1)
                 for i in sorted(identity)]
    plan = dict(status='proposal only; no forwards executed', source_manifest_sha256=sha(manifest_path),
                calibration_roi_freeze_sha256=sha(calib_path), calibration_roi_indices=calibration_rois,
                calibration_sample_indices=sorted(calibration_ids), evaluation_sample_indices=sorted(identity),
                calibration_order_sample_indices=[manifest[i]['sample_index'] for i in calibration_rois],
                counts=dict(calibration_fp32=207, additional_evaluation_fp32=97, evaluation_integer=304,
                            fp32_total=304, integer_total=304, detector_total_max=608,
                            optimizer_steps=0, cnn_forwards=0, ocr_forwards=0,
                            validation84_images=0, heldout112_images=0), identities=plan_rows,
                freeze_before_evaluation=['all tensor scales/zero points', 'W8/bias/M/shift',
                                         'SiLU and head LUTs', 'concat scale edges', 'overflow proofs'],
                only_candidate='per-channel W8, per-tensor affine A8 minmax, 63 SiLU LUTs and 3 head LUT groups')
    budget_path = ROOT / 'docs/validation/blue-plate/whole-plate-budget/detector-sharing.json'
    budget = read(budget_path)
    original_constants = budget['traffic']['constants_materialization_read_and_write'] // 2
    zero_bytes = sum(h['eliminated_zero_bytes'] for h in head_rows)
    lut_bytes = len(silu) * 256 + sum(h['proposed_tables']['total_bytes'] for h in head_rows)
    assert (original_constants, zero_bytes, lut_bytes) == (529280, 378000, 59136)
    assert original_constants - zero_bytes + lut_bytes <= original_constants
    summary = dict(model_sha256=sha(MODEL), ir=model.ir_version,
                   opsets=[dict(domain=x.domain, version=x.version) for x in model.opset_import],
                   original_nodes=len(nodes), op_counts=dict(Counter(n.op_type for n in nodes)),
                   original_initializers=len(arrays), value_info=len(graph.value_info),
                   original_all_runtime_tensors_float32=True, original_has_quantization_nodes=False,
                   opencv_expanded_nodes=len(old), convolutions=85, depthwise=19,
                   silu_groups=63, core_concats=25, backbone_residual_adds=0,
                   head_adds=adds, macs=sum(c['macs'] for c in convs),
                   mac8_ideal_cycles=sum(c['mac8_cycles'] for c in convs),
                   conv_requant_outputs=sum(c['output_elements'] for c in convs),
                   silu_lookups=sum(math.prod(tensors[x['output']]['shape']) for x in silu.values()),
                   concat_edge_elements_upper_bound=sum(c['elements'] for c in concats),
                   maximum_K=max(c['K'] for c in convs), maximum_weight_tile=max(c['weight_tile_bytes'] for c in convs),
                   constant_storage=dict(existing_bytes=original_constants, exact_zero_bytes=zero_bytes,
                                         proposed_lut_bytes=lut_bytes,
                                         conservative_retained_constants_plus_luts=original_constants-zero_bytes+lut_bytes),
                   unchanged_budgets=dict(engine_dsp=8, engine_ram10=51, full_arena_bytes=7052352,
                                          detector_temporary_high_water_bytes=1536000),
                   audit_counters=dict(image_bytes_read=0, model_forwards=0, parameter_exports=0, optimizer_steps=0),
                   parser_versions=dict(onnx=onnx.__version__, numpy=np.__version__),
                   checks=['ONNX checker', 'all 85 conv shapes/weights/MACs match cached OpenCV inventory',
                           'all SiLU topologies', 'all anchors/grid/zero constants', 'identity split and calibration membership'])
    initializer_rows = [dict(name=k, shape=list(a.shape), dtype=str(a.dtype), bytes=a.nbytes,
                             minimum=float(a.min()) if a.size else None, maximum=float(a.max()) if a.size else None,
                             sha256_c_order_bytes=hashlib.sha256(a.tobytes()).hexdigest(),
                             values=a.tolist() if a.size <= 16 else None) for k, a in arrays.items()]
    sources = [Path(__file__), MODEL, manifest_path, calib_path, budget_path,
               ROOT/'tools/blue_plate/whole_plate_budget/detector_sharing.py',
               ROOT/'tmp/blue-plate-normal-g1/mature-detector/model-costs.json',
               ROOT/'tmp/blue-plate-review/mature-research/hyperlpr/Prj-Python/hyperlpr3/inference/multitask_detect.py',
               *RESEARCH.glob('*.h'), *RESEARCH.glob('*.cc'), RESEARCH/'new-sources.json', RESEARCH/'parser-packages.json']
    OUT.mkdir()
    for name, value in [('summary.json', summary), ('nodes.json', rows), ('convolutions.json', convs),
                        ('concat-scales.json', concats), ('silu.json', silu), ('head-decode.json', head_rows),
                        ('initializers.json', initializer_rows), ('bounded-plan.json', plan)]:
        write(name, value)
    write('source-hashes.json', {p.relative_to(ROOT).as_posix(): sha(p) for p in sources})
    assert sha(MODEL) == EXPECTED_SHA
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
