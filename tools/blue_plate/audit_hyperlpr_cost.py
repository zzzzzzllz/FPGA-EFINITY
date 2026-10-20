"""Count grouped convolution and matrix products from inspected model shapes."""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'tmp/blue-plate-normal-g1/mature-detector'


def main():
    source = OUT/'model-costs.json'
    models = json.loads(source.read_text(encoding='utf8'))
    report = {}
    for name, model in models.items():
        matmul = weights = bias = peak = 0
        for row in model['layers']:
            peak = max(peak, max((math.prod(shape) for shape in row['outputs']), default=0))
            if row['type'] == 'MatMul':
                matmul += math.prod(row['outputs'][0])*row['inputs'][0][-1]
            if row['type'] in ['Convolution', 'MatMul'] and row['blobs']:
                weights += math.prod(row['blobs'][0])
                bias += sum(math.prod(shape) for shape in row['blobs'][1:])
        macs = model['convolution_macs']+matmul
        report[name] = dict(convolution_macs=model['convolution_macs'], matmul_macs=matmul,
                            total_macs=macs, weight_elements=weights, bias_elements=bias,
                            int8_weights_int32_bias_bytes=weights+4*bias,
                            max_single_blob_elements=peak,
                            ideal_ms_43_dsp_100mhz_1mac=macs/(43*100000),
                            ideal_ms_43_dsp_100mhz_dual8bit=macs/(86*100000))
    report['scope'] = ('Conv and MatMul MACs only; excludes nonlinear/normalization, DMA, buffering, '
                       'schedule stalls, quantization accuracy and synthesis. Remaining 43 DSP is a ceiling '
                       'before geometry/other new kernels. Dual INT8 is device capability, not achieved throughput.')
    report['model_cost_source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    report['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (OUT/'resource-audit.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
