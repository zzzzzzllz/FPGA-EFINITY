"""Outward integer probability bounds; Q128 is an offline proof oracle only."""
from fractions import Fraction


def ceil_div(n, d):
    assert n >= 0 and d > 0
    return (n+d-1)//d


def rational_bounds(value, bits):
    scale = 1 << bits
    n, d = value.numerator*scale, value.denominator
    return n//d, ceil_div(n, d)


def exp_certificate(x, bits=128):
    """Alternating rational Taylor bounds on exp(-x), followed by outward squaring."""
    assert isinstance(x, Fraction) and x >= 0
    scale = 1 << bits
    if x == 0:
        return dict(squarings=0, y_numerator='0', y_denominator='1', lower=str(scale), upper=str(scale))
    y, k = x, 0
    while y > Fraction(1, 8):
        y /= 2
        k += 1
    term = total = Fraction(1)
    upper = None
    for n in range(1, 32):
        previous = term
        term = -term*y/n
        assert abs(term) < abs(previous)
        total += term
        if n == 30:
            upper = total
    lower = total
    assert 0 < lower <= upper <= 1 and 0 < y <= Fraction(1, 8)
    lo = rational_bounds(lower, bits)[0]
    hi = rational_bounds(upper, bits)[1]
    for _ in range(k):
        lo, hi = lo*lo//scale, ceil_div(hi*hi, scale)
    assert 0 <= lo <= hi <= scale
    return dict(squarings=k, y_numerator=str(y.numerator), y_denominator=str(y.denominator),
                lower=str(lo), upper=str(hi))


def collapse(path, blank):
    return [c for i,c in enumerate(path) if c != blank and (i == 0 or c != path[i-1])]


def emissions(differences, table, bits, stats=None):
    scale = 1 << bits
    result = []
    for row in differences:
        bounds = [table[int(d)] for d in row]
        sum_lo = sum(v[0] for v in bounds)
        sum_hi = sum(v[1] for v in bounds)
        assert 0 < sum_lo <= sum_hi <= len(row)*scale
        probability = [(a*scale//sum_hi, min(scale, ceil_div(b*scale, sum_lo))) for a,b in bounds]
        assert all(0 <= a <= b <= scale for a,b in probability)
        result.append(probability)
        if stats is not None:
            stats['softmax_sum_bits'] = max(stats.get('softmax_sum_bits', 0), sum_hi.bit_length())
            stats['softmax_numerator_bits'] = max(stats.get('softmax_numerator_bits', 0), max(b*scale for _,b in bounds).bit_length())
    return result


def ctc_bounds(probabilities, target, bits, blank=67, stats=None):
    scale = 1 << bits
    assert all(c != blank for c in target)
    extended = [blank]
    for c in target:
        extended.extend([c, blank])
    previous = [(0,0)]*len(extended)
    previous[0] = (scale, scale)
    for row in probabilities:
        current = []
        for s,c in enumerate(extended):
            sources = [previous[s]]
            if s:
                sources.append(previous[s-1])
            if s >= 2 and c != blank and c != extended[s-2]:
                sources.append(previous[s-2])
            a, b = sum(x[0] for x in sources), sum(x[1] for x in sources)
            lo, hi = row[c]
            products = a*lo, b*hi
            pair = products[0]//scale, min(scale, ceil_div(products[1], scale))
            assert 0 <= pair[0] <= pair[1] <= scale
            current.append(pair)
            if stats is not None:
                stats['dp_sum_bits'] = max(stats.get('dp_sum_bits', 0), b.bit_length())
                stats['dp_product_bits'] = max(stats.get('dp_product_bits', 0), products[1].bit_length())
        previous = current
    last = previous[-2:] if target else previous[-1:]
    return sum(x[0] for x in last), min(scale, sum(x[1] for x in last))


def decision(bounds, threshold, bits=30):
    lo, hi = bounds
    if Fraction(lo, 1 << bits) >= threshold:
        return 'accept'
    if Fraction(hi, 1 << bits) < threshold:
        return 'reject'
    return 'undecided'


def rank_candidates(rows):
    """Only dominance or a proved exact tie can discard a potential winner."""
    possible, ties = [], []
    for row in rows:
        dominated = False
        for other in rows:
            if other['roi_index'] == row['roi_index']:
                continue
            a,b = row['bounds'],other['bounds']
            point_tie = a[0] == a[1] == b[0] == b[1]
            input_tie = row.get('signature') is not None and row.get('signature') == other.get('signature')
            if b[0] > a[1]:
                dominated = True
            elif (point_tie or input_tie) and other['roi_index'] < row['roi_index']:
                dominated = True
                ties.append(dict(lower_roi=other['roi_index'], higher_roi=row['roi_index'],
                                 proof='exact_point' if point_tie else 'identical_logits_and_target'))
        if not dominated:
            possible.append(row['roi_index'])
    assert not rows or possible
    return dict(status='no_candidate' if not rows else 'selected' if len(possible)==1 else 'undecided',
                selected_roi_index=possible[0] if len(possible)==1 else None,
                possible_roi_indices=sorted(possible), exact_tie_proofs=ties)
