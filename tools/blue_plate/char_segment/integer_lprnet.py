"""Research W8/A8 integer arithmetic; CTC confidence is deliberately outside this core."""
import math

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from torch.nn.utils.fusion import fuse_conv_bn_weights

TAPS = {'backbone.2': 0, 'backbone.6': 1, 'backbone.13': 2, 'backbone.22': 3}
POOLS = [((5, 5), (5, 5)), ((5, 5), (5, 5)), ((4, 10), (4, 2)), ((1, 1), (1, 1))]


def round_ratio(n, d):
    if d <= 0:
        raise ValueError('Positive integer denominator required')
    q, r = divmod(int(n), int(d))
    return q + int(2*r > d or (2*r == d and q & 1))


def round_tensor(n, d):
    q = torch.div(n, d, rounding_mode='floor')
    r = n-q*d
    return q + ((2*r > d) | ((2*r == d) & ((q & 1) != 0))).long()


def affine(lo, hi):
    lo, hi = min(0., lo), max(0., hi)
    if not math.isfinite(lo+hi) or hi < lo:
        raise ValueError('Invalid calibration range')
    if hi == lo:
        return dict(scale=1., zero=0, constant_zero=True)
    scale = max((hi-lo)/255, float(np.finfo(np.float32).eps))
    return dict(scale=scale, zero=int(np.clip(-128-round(lo/scale), -128, 127)), constant_zero=False)


def graph(net):
    leaves = [(name, module) for name, module in net.named_modules() if not list(module.children())]
    stages = []
    i = 0
    while i < len(leaves):
        name, m = leaves[i]
        if isinstance(m, nn.Conv2d):
            stage = dict(name=name, kind='conv', end=name, bn=None, relu=False,
                         kernel=list(m.kernel_size), padding=list(m.padding))
            assert m.groups == 1 and m.stride == (1, 1) and m.dilation == (1, 1)
            if i+1 < len(leaves) and isinstance(leaves[i+1][1], nn.BatchNorm2d):
                i += 1
                stage['bn'] = stage['end'] = leaves[i][0]
            if i+1 < len(leaves) and isinstance(leaves[i+1][1], nn.ReLU):
                i += 1
                stage['relu'] = True
                stage['end'] = leaves[i][0]
            stage['tap'] = TAPS.get(stage['end'])
            stages.append(stage)
        elif isinstance(m, nn.MaxPool3d):
            assert m.kernel_size == (1, 3, 3)
            stages.append(dict(name=name, end=name, kind='maxpool', channel_stride=m.stride[0],
                               spatial_stride=list(m.stride[1:]), tap=None))
        elif not isinstance(m, nn.Dropout):
            raise ValueError(f'Unexpected unfused module: {name} {m}')
        i += 1
    assert len([s for s in stages if s['kind'] == 'conv']) == 16
    return stages


class FloatTrace:
    def __init__(self, net, stages):
        self.net, self.stages, self.values = net, stages, {}
        modules = dict(net.named_modules())
        self.handles = []
        for s in stages:
            def capture(module, inputs, output, key=s['name']):
                self.values[key] = output.detach()
            self.handles.append(modules[s['end']].register_forward_hook(capture))

    @torch.inference_mode()
    def __call__(self, resized):
        self.values = {}
        x = (torch.from_numpy(resized.transpose(2, 0, 1).copy()).float()[None]-127.5)/128
        logits = self.net(x)
        self.values['input'] = x
        normals = []
        for stage in self.stages:
            if stage['tap'] is None:
                continue
            i = stage['tap']
            avg = F.avg_pool2d(self.values[stage['name']], *POOLS[i])
            normal = avg / avg.square().mean()
            self.values[f'context.{i}.average'] = avg
            self.values[f'context.{i}.normalized'] = normal
            normals.append(normal)
        self.values['concat'] = torch.cat(normals, 1)
        self.values['logits'] = logits
        return self.values

    def close(self):
        for handle in self.handles:
            handle.remove()


def make_parameters(net, stages, ranges):
    modules = dict(net.named_modules())
    config = dict(stages=[], taps={}, context=affine(*ranges['concat']), rounding='nearest_ties_to_even')
    arrays = {}
    previous = dict(scale=1/128, zero=0)
    for stage in stages:
        s = dict(stage)
        if s['kind'] == 'maxpool':
            s['output'] = previous
        else:
            if s['name'] == 'container.0':
                previous = config['context']
            conv = modules[s['name']]
            w, b = conv.weight.detach(), conv.bias.detach()
            if s['bn'] is not None:
                bn = modules[s['bn']]
                w, b = fuse_conv_bn_weights(w, b, bn.running_mean, bn.running_var, bn.eps, bn.weight, bn.bias)
            w, b = w.detach().double().numpy(), b.detach().double().numpy()
            if s['name'] == 'backbone.0':
                assert s['padding'] == [0, 0]
                b = b + w.sum(axis=(1, 2, 3)) / 256
            maxima = np.max(np.abs(w), axis=(1, 2, 3))
            # Match the inspected PyTorch observer's minimum scale for near-zero channels.
            ws = np.maximum(maxima/127, float(np.finfo(np.float32).eps))
            qw = np.clip(np.rint(w/ws[:, None, None, None]), -127, 127).astype(np.int8)
            output = affine(*ranges[s['name']])
            bias_float = np.rint(b/(previous['scale']*ws))
            if not np.isfinite(bias_float).all() or np.max(np.abs(bias_float)) >= 1 << 31:
                raise ValueError(f'Bias cannot fit int32: {s["name"]}')
            bias = bias_float.astype(np.int64)
            corrected = bias - previous['zero']*qw.astype(np.int64).sum(axis=(1, 2, 3))
            multipliers, shifts = [], []
            for multiplier in previous['scale']*ws/output['scale']:
                fraction, exponent = math.frexp(float(multiplier))
                integer = round(fraction*(1 << 31))
                if integer == 1 << 31:
                    integer //= 2
                    exponent += 1
                shift = 31-exponent
                if not 1 <= shift <= 62:
                    raise ValueError(f'Unsupported fixed multiplier shift: {shift}')
                multipliers.append(integer)
                shifts.append(shift)
            k = int(np.prod(qw.shape[1:]))
            bound = k*128*127 + int(np.abs(corrected).max())
            assert bound < 1 << 31 and bound*max(multipliers) < 1 << 63
            prefix = s['name']
            arrays.update({prefix+'.weight': qw, prefix+'.bias': corrected.astype(np.int32),
                           prefix+'.multiplier': np.asarray(multipliers, np.int64),
                           prefix+'.shift': np.asarray(shifts, np.int64)})
            s.update(input=previous, output=output, weight_scales=ws.tolist(), zero_weight_channels=int((maxima == 0).sum()),
                     scale_floor_channels=int((maxima/127 < np.finfo(np.float32).eps).sum()),
                     shape=list(qw.shape), mac_terms=k, accumulator_abs_bound=bound,
                     accumulator_signed_bits=bound.bit_length()+1)
            previous = output
        config['stages'].append(s)
        if s['tap'] is not None:
            i = s['tap']
            k = math.prod(POOLS[i][0])
            constant = round(k/(previous['scale']*config['context']['scale'])*(1 << 30))
            config['taps'][str(i)] = dict(stage=s['name'], quantization=previous, kernel=list(POOLS[i][0]),
                stride=list(POOLS[i][1]), area=k, constant_q30=constant,
                pool_scale=previous['scale']/k)
    config['logit_scale'] = previous['scale']/4
    return config, arrays


def patches(q, kernel, padding):
    h, w = kernel
    py, px = padding
    return q.unfold(2, h, 1).unfold(3, w, 1).permute(0, 2, 3, 1, 4, 5).reshape(-1, q.shape[1]*h*w).contiguous()


class IntegerLPR:
    def __init__(self, config, arrays):
        self.config = config
        self.parameters = {k: torch.from_numpy(v.copy()) for k, v in arrays.items()}

    def conv(self, q, stage, vectors=None):
        name = stage['name']
        weight = self.parameters[name+'.weight']
        bias = self.parameters[name+'.bias']
        py, px = stage['padding']
        padded = F.pad(q, (px, px, py, py), value=stage['input']['zero'])
        a = patches(padded, stage['kernel'], stage['padding'])
        w = weight.reshape(weight.shape[0], -1).T.contiguous()
        accum = torch._int_mm(a, w).long() + bias.long()
        assert int(accum.abs().max()) <= stage['accumulator_abs_bound']
        if vectors is not None and name in ('backbone.0', 'backbone.4.block.0', 'backbone.20', 'container.0'):
            for pos in (0, len(a)//2, len(a)-1):
                for channel in (0, weight.shape[0]//2, weight.shape[0]-1):
                    scalar = int(bias[channel]) + sum(int(x)*int(y) for x, y in zip(a[pos], w[:, channel]))
                    assert scalar == int(accum[pos, channel])
                    vectors.append(dict(layer=name, position=pos, channel=channel, a=a[pos].numpy().copy(),
                        w=w[:, channel].numpy().copy(), initial_accumulator=int(bias[channel]), accumulator=scalar,
                        multiplier=int(self.parameters[name+'.multiplier'][channel]),
                        right_shift=int(self.parameters[name+'.shift'][channel]),
                        output_zero=stage['output']['zero'], relu=stage['relu']))
        requant_input = accum.clamp(min=0) if stage['relu'] else accum
        product = requant_input*self.parameters[name+'.multiplier']
        denominator = torch.bitwise_left_shift(torch.ones_like(self.parameters[name+'.shift']), self.parameters[name+'.shift'])
        unbounded = round_tensor(product, denominator) + stage['output']['zero']
        stats = dict(accumulator_min=int(accum.min()), accumulator_max=int(accum.max()),
                     saturated=int(((unbounded < -128) | (unbounded > 127)).sum()), elements=unbounded.numel())
        output = unbounded.clamp(-128, 127).to(torch.int8)
        oh = padded.shape[2]-stage['kernel'][0]+1
        ow = padded.shape[3]-stage['kernel'][1]+1
        return output.T.reshape(1, weight.shape[0], oh, ow), stats

    def context_head(self, taps, trace, statistics, vectors=None):
        normalized = []
        context = self.config['context']
        for i in range(4):
            meta = self.config['taps'][str(i)]
            q = taps[i].long()-meta['quantization']['zero']
            kh, kw = meta['kernel']
            sh, sw = meta['stride']
            v = q.unfold(2, kh, sh).unfold(3, kw, sw).sum(dim=(-1, -2))
            energy = int(v.square().sum())
            if energy == 0:
                raise ValueError(f'Zero quantized energy in context branch {i}')
            numerator = meta['constant_q30']*v.numel()
            gain = round_ratio(numerator, energy)
            assert int(v.abs().max())*gain < 1 << 63
            unbounded = round_tensor(v*gain, 1 << 30) + context['zero']
            out = unbounded.clamp(-128, 127).to(torch.int8)
            trace[f'context.{i}.average'] = (v, meta['pool_scale'], 0)
            trace[f'context.{i}.normalized'] = (out, context['scale'], context['zero'])
            statistics[f'context.{i}.normalized'] = dict(energy_sum=energy, energy_bits=energy.bit_length(),
                reciprocal_numerator_bits=numerator.bit_length(), gain_q30=gain,
                gain_bits=gain.bit_length(), multiply_abs_bound=int(v.abs().max())*gain,
                saturated=int(((unbounded < -128) | (unbounded > 127)).sum()), elements=out.numel())
            normalized.append(out)
        concat = torch.cat(normalized, 1)
        trace['concat'] = (concat, context['scale'], context['zero'])
        stage = self.config['stages'][-1]
        assert stage['name'] == 'container.0'
        head, statistics[stage['name']] = self.conv(concat, stage, vectors)
        trace[stage['name']] = (head, stage['output']['scale'], stage['output']['zero'])
        assert head.shape[2] == 4
        logits = (head.long()-stage['output']['zero']).sum(dim=2)
        assert int(logits.abs().max()) <= 1020
        trace['logits'] = (logits, self.config['logit_scale'], 0)
        return logits.to(torch.int16)

    def __call__(self, resized, capture_vectors=False):
        if resized.dtype != np.uint8 or resized.shape != (24, 94, 3):
            raise ValueError('Expected frozen Q8 uint8 BGR 24x94')
        q = torch.from_numpy((resized.transpose(2, 0, 1).astype(np.int16)-128).astype(np.int8))[None]
        trace, statistics, taps = {}, {}, {}
        vectors = [] if capture_vectors else None
        for stage in self.config['stages'][:-1]:
            if stage['kind'] == 'conv':
                q, statistics[stage['name']] = self.conv(q, stage, vectors)
            else:
                sh, sw = stage['spatial_stride']
                q = q.unfold(2, 3, sh).unfold(3, 3, sw).amax(dim=(-1, -2))[:, ::stage['channel_stride']]
            trace[stage['name']] = (q, stage['output']['scale'], stage['output']['zero'])
            if stage['tap'] is not None:
                taps[stage['tap']] = q
        logits = self.context_head(taps, trace, statistics, vectors)
        return logits, trace, statistics, vectors


def dequantize(item):
    q, scale, zero = item
    return (q.double()-zero)*scale
