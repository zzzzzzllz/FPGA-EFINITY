"""One tap2 dual-consumer candidate, preserving the frozen first integer core."""
import copy
import math

import numpy as np
import torch
from torch.nn import functional as F
from torch.nn.utils.fusion import fuse_conv_bn_weights

from integer_lprnet import IntegerLPR, affine, patches, round_tensor

FORK = 'backbone.11.block.6'
TRUNK = 'tap2.trunk'


def multipliers(ratios):
    ms, shifts = [], []
    for ratio in ratios:
        fraction, exponent = math.frexp(float(ratio))
        m = round(fraction*(1 << 31))
        if m == 1 << 31:
            m //= 2
            exponent += 1
        shift = 31-exponent
        assert 1 <= shift <= 62
        ms.append(m)
        shifts.append(shift)
    return np.array(ms, np.int64), np.array(shifts, np.int64)


def fork_parameters(net, original_config, original_arrays, selected_range):
    config = copy.deepcopy(original_config)
    arrays = {k: v.copy() for k, v in original_arrays.items()}
    scale = affine(*selected_range)
    assert scale['zero'] == -128
    stage = next(s for s in config['stages'] if s['name'] == FORK)
    ratios = stage['input']['scale']*np.array(stage['weight_scales'])[::4]/scale['scale']
    arrays[TRUNK+'.multiplier'], arrays[TRUNK+'.shift'] = multipliers(ratios)
    assert stage['accumulator_abs_bound']*int(arrays[TRUNK+'.multiplier'].max()) < 1 << 63
    config['fork'] = dict(stage=FORK, channels=list(range(0, 256, 4)), output=scale,
                          range_before_maxpool=list(selected_range))
    pool = next(s for s in config['stages'] if s['name'] == 'backbone.14')
    pool['output'] = scale
    pool['channel_stride'] = 1  # The fork has already selected channels 0,4,...,252.
    downstream = next(s for s in config['stages'] if s['name'] == 'backbone.16')
    downstream['input'] = scale
    modules = dict(net.named_modules())
    conv, bn = modules['backbone.16'], modules[downstream['bn']]
    _, b = fuse_conv_bn_weights(conv.weight, conv.bias, bn.running_mean, bn.running_var,
                                bn.eps, bn.weight, bn.bias)
    ws = np.array(downstream['weight_scales'])
    bias = np.rint(b.detach().double().numpy()/(scale['scale']*ws))
    assert np.isfinite(bias).all() and np.abs(bias).max() < 1 << 31
    qw = arrays['backbone.16.weight']
    bias = bias.astype(np.int64)-scale['zero']*qw.astype(np.int64).sum(axis=(1, 2, 3))
    bound = downstream['mac_terms']*128*127+int(np.abs(bias).max())
    arrays['backbone.16.bias'] = bias.astype(np.int32)
    arrays['backbone.16.multiplier'], arrays['backbone.16.shift'] = multipliers(scale['scale']*ws/downstream['output']['scale'])
    assert bound < 1 << 31 and bound*int(arrays['backbone.16.multiplier'].max()) < 1 << 63
    downstream.update(accumulator_abs_bound=bound, accumulator_signed_bits=bound.bit_length()+1)
    changed = {k for k in original_arrays if not np.array_equal(arrays[k], original_arrays[k])}
    assert changed <= {'backbone.16.bias', 'backbone.16.multiplier', 'backbone.16.shift'}
    return config, arrays


class ForkLPR(IntegerLPR):
    def fork_conv(self, q, stage):
        weight = self.parameters[FORK+'.weight']
        assert stage['kernel'] == [1, 1] and stage['padding'] == [0, 0] and stage['relu']
        a = patches(q, stage['kernel'], stage['padding'])
        accum = torch._int_mm(a, weight.reshape(256, 64).T.contiguous()).long()+self.parameters[FORK+'.bias'].long()
        assert int(accum.abs().max()) <= stage['accumulator_abs_bound']
        outputs, statistics = [], {}
        for name, values, output in ((FORK, accum, stage['output']),
                                     (TRUNK, accum[:, ::4], self.config['fork']['output'])):
            product = values.clamp(min=0)*self.parameters[name+'.multiplier']
            shifts = self.parameters[name+'.shift']
            denominator = torch.bitwise_left_shift(torch.ones_like(shifts), shifts)
            unbounded = round_tensor(product, denominator)+output['zero']
            statistics[name] = dict(accumulator_min=int(values.min()), accumulator_max=int(values.max()),
                                    saturated=int(((unbounded < -128) | (unbounded > 127)).sum()), elements=unbounded.numel())
            outputs.append(unbounded.clamp(-128, 127).to(torch.int8).T.reshape(1, values.shape[1], q.shape[2], q.shape[3]))
        return outputs, statistics, accum

    def __call__(self, resized, capture_vectors=False):
        if resized.dtype != np.uint8 or resized.shape != (24, 94, 3):
            raise ValueError('Expected frozen Q8 uint8 BGR 24x94')
        q = torch.from_numpy((resized.transpose(2, 0, 1).astype(np.int16)-128).astype(np.int8))[None]
        trace, statistics, taps, vectors = {}, {}, {}, {}
        trunk = None
        for stage in self.config['stages'][:-1]:
            name = stage['name']
            if name == FORK:
                old_input = q
                (q, trunk), fork_stats, accum = self.fork_conv(q, stage)
                statistics.update(fork_stats)
                trace[TRUNK] = (trunk, self.config['fork']['output']['scale'], self.config['fork']['output']['zero'])
                if capture_vectors:
                    vectors.update(input=old_input.numpy(), accumulator=accum[:, ::4].T.reshape(1, 64, 18, 44).int().numpy(),
                                   context=q.numpy(), trunk=trunk.numpy())
            elif stage['kind'] == 'conv':
                q, statistics[name] = self.conv(q, stage)
            else:
                if name == 'backbone.14':
                    assert trunk is not None
                    q, trunk = trunk, None
                sh, sw = stage['spatial_stride']
                q = q.unfold(2, 3, sh).unfold(3, 3, sw).amax(dim=(-1, -2))[:, ::stage['channel_stride']]
                if capture_vectors and name == 'backbone.14':
                    vectors['pooled'] = q.numpy()
            trace[name] = (q, stage['output']['scale'], stage['output']['zero'])
            if stage['tap'] is not None:
                taps[stage['tap']] = q
        logits = self.context_head(taps, trace, statistics)
        return logits, trace, statistics, vectors
