"""Integer character interface. IDs follow CCPD province order then letters/digits."""
from pathlib import Path
import numpy as np

CLASSES = '皖沪津渝冀晋蒙辽吉黑苏浙京闽赣鲁豫鄂湘粤桂琼川贵云藏陕甘青宁新ABCDEFGHJKLMNPQRSTUVWXYZ0123456789'


def normalize(mask, mode='square'):
    """Foreground=1; tight bbox; nearest floor sampling; integer half-up scaling."""
    mask = np.asarray(mask)
    if mask.ndim != 2 or not np.isin(mask, [0, 1]).all():
        raise ValueError('Expected a 2-D binary foreground mask')
    yy, xx = np.where(mask)
    if len(xx) < 4:
        raise ValueError('Blank/insufficient foreground')
    tight = mask[yy.min():yy.max()+1, xx.min():xx.max()+1]
    h, w = tight.shape
    limit_x, limit_y = (14, 28) if mode == 'legacy' else (28, 28)
    if w*limit_y >= h*limit_x:
        nw, nh = limit_x, max(1, (h*limit_x+w//2)//w)
    else:
        nw, nh = max(1, (w*limit_y+h//2)//h), limit_y
    width = 16 if mode == 'legacy' else 32
    out = np.zeros((32, width), np.uint8)
    oy, ox = (32-nh)//2, (width-nw)//2
    out[oy:oy+nh, ox:ox+nw] = tight[np.arange(nh)[:, None]*h//nh, np.arange(nw)[None, :]*w//nw]
    return out


def features(mask):
    """320 unsigned six-bit values: 256 2x2 sums*8, 32 columns, 32 rows."""
    mask = np.asarray(mask)
    if mask.shape != (32, 32) or not np.isin(mask, [0, 1]).all():
        raise ValueError('Expected 32x32 binary normalized input')
    grid = mask.reshape(16, 2, 16, 2).sum(axis=(1, 3))*8
    return np.concatenate([grid.ravel(), mask.sum(axis=0), mask.sum(axis=1)]).astype(np.int32)


def allowed_ids(position):
    if position not in range(7):
        raise ValueError('Character position must be 0..6')
    return np.arange(31) if position == 0 else np.arange(31, 55 if position == 1 else 65)


def integer_scores(x, weights):
    x = np.asarray(x, dtype=np.int64)
    if x.shape[-1] != 320 or np.any(x < 0) or np.any(x > 32):
        raise ValueError('Expected feature vector(s) in 0..32')
    first = x @ weights['w1'].astype(np.int64) + weights['b1']
    if 'w2' not in weights:
        return first
    hidden = np.clip((first+128)//256, 0, 255)
    return hidden @ weights['w2'].astype(np.int64) + weights['b2']


def predict(mask, position, model_dir):
    """Accept a raw cropped binary ROI and normalize exactly once.

    Canonical test-vector input must go directly to features/integer_scores/decide.
    Nearest sampling can drop a boundary pixel, so normalize is not idempotent.
    """
    import json
    model_dir = Path(model_dir)
    config = json.loads((model_dir/'interface.json').read_text(encoding='utf8'))
    weights = dict(np.load(model_dir/'weights.npz'))
    norm = normalize(mask)
    scores = integer_scores(features(norm), weights)
    return decide(scores, position, config['thresholds'])


def decide(scores, position, thresholds):
    scores = np.asarray(scores)
    if scores.shape != (65,):
        raise ValueError('Expected 65 class scores')
    ids = allowed_ids(position)
    ranked = ids[np.argsort(-scores[ids], kind='stable')]
    best, second = map(int, ranked[:2])
    margin = int(scores[best]-scores[second])
    threshold = thresholds['province' if position == 0 else 'alphanumeric']
    ok = int(scores[best]) >= threshold['score'] and margin >= threshold['margin']
    return dict(id=best, char=CLASSES[best], score=int(scores[best]), margin=margin, accepted=ok)
