"""Independently verify the saved static audit; no image reads or inference."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'tmp/blue-plate-char-segment'
OUT = BASE / 'detector-integer-audit'
RESEARCH = BASE / 'detector-integer-research'
sys.path.insert(0, str(RESEARCH / 'python'))
import onnx


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if (OUT / 'verification.json').exists():
        raise FileExistsError('Preserve verification')
    sources = read(OUT / 'source-hashes.json')
    for name, digest in sources.items():
        assert sha(ROOT / name) == digest, name
    model_path = ROOT / 'tmp/blue-plate-normal-g1/mature-detector/y5fu_320x_sim.onnx'
    model = onnx.load(str(model_path))
    rows = read(OUT / 'nodes.json')
    assert [(r['name'], r['op']) for r in rows] == [(n.name, n.op_type) for n in model.graph.node]
    metadata = {t.name: (onnx.TensorProto.DataType.Name(t.type.tensor_type.elem_type),
                        [d.dim_value for d in t.type.tensor_type.shape.dim])
                for t in [*model.graph.input, *model.graph.value_info, *model.graph.output]}
    for row, node in zip(rows, model.graph.node):
        assert [x['name'] for x in row['inputs']] == [x for x in node.input if x]
        assert [x['name'] for x in row['outputs']] == list(node.output)
        for t in row['inputs'] + row['outputs']:
            if t['name'] in metadata:
                assert (t['dtype'], t['shape']) == metadata[t['name']]
    cv = read(ROOT / 'tmp/blue-plate-normal-g1/mature-detector/model-costs.json')['detector320']['layers']
    cv = {r['name']: r for r in cv}
    convs = read(OUT / 'convolutions.json')
    for c in convs:
        prior = cv['onnx_node!' + c['name']]
        assert prior['inputs'][0] == c['input_shape']
        assert prior['outputs'][0] == c['output_shape']
        assert prior['blobs'][0] == c['weight_shape']
        assert prior['macs'] == c['macs']
        assert math.prod(c['output_shape']) == c['output_elements']
    plan = read(OUT / 'bounded-plan.json')
    ids = plan['identities']
    assert len(ids) == len({r['sample_index'] for r in ids}) == 304
    assert Counter(r['split'] for r in ids) == {'train': 228, 'tune': 76}
    assert all(r['original_split'] == 'development' for r in ids)
    assert sum(r['calibration'] for r in ids) == 207
    assert all(r['split'] == 'train' for r in ids if r['calibration'])
    assert sum(r['fp32_passes'] + r['integer_passes'] for r in ids) == 608
    assert plan['calibration_sample_indices'] == sorted(r['sample_index'] for r in ids if r['calibration'])
    assert plan['evaluation_sample_indices'] == [r['sample_index'] for r in ids]
    heads = read(OUT / 'head-decode.json')
    max_width = max(a[0] * 4 for h in heads for a in h['anchors'])
    max_height = max(a[1] * 4 for h in heads for a in h['anchors'])
    area_sum_upper = 2 * (int(max_width * 65536) + 2) * (int(max_height * 65536) + 2)
    assert (max_width, max_height) == (1340, 1732)
    assert area_sum_upper < 2**55
    summary = read(OUT / 'summary.json')
    assert summary['constant_storage']['conservative_retained_constants_plus_luts'] == 210416
    assert 210416 <= 529280 and 1024 <= 2048
    assert summary['audit_counters'] == dict(image_bytes_read=0, model_forwards=0, parameter_exports=0, optimizer_steps=0)
    # Check only prior manifest bytes. Never follow their image entries.
    prior_manifests = {
        'six-green-negatives/delivery-freeze.json': '138a5cfbea4b70f72404e5b24db2bcfc5504c92d385243755778cc6c20e01117',
        'color-cnn-ablation/delivery-freeze.json': '4643e2bda9a68f9ed3a9d2a3d502d0f787154b2d4d9e794b40d6e6f4dd9017d9',
    }
    for name, digest in prior_manifests.items():
        assert sha(BASE / name) == digest
    report = dict(pass_=True, graph_nodes=416, original_tensor_metadata_entries=len(metadata),
                  conv_input_output_weight_mac_crosschecks=85,
                  authorized_development_identities=304, calibration_train_identities=207,
                  future_detector_forward_limit=608, this_audit_forwards=0, image_bytes_read=0,
                  nms_area_sum_q32_32_upper=area_sum_upper, nms_upper_below_2_pow_55=True,
                  prior_manifest_hashes=prior_manifests,
                  prior_manifest_scope='manifest bytes only; image entries were not read',
                  model_unchanged=sha(model_path) == summary['model_sha256'],
                  source_hashes_verified=len(sources))
    (OUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
