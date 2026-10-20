"""Content-disjoint EasyPR character experiment; no CCPD acceptance labels used.

Offline training uses installed sklearn. Inference uses model.py integer MACs.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '2')
os.environ.setdefault('OMP_NUM_THREADS', '2')
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time
import cv2
import numpy as np
from sklearn.cluster import KMeans
from sklearn.neural_network import MLPClassifier
from sklearn.svm import LinearSVC
from threadpoolctl import threadpool_limits
from model import CLASSES, features, normalize, integer_scores

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT/'tmp/blue-plate-g1'
OUT = ROOT/'tmp/blue-plate-char-model'
sys.path.insert(0, str(ROOT/'tools/blue_plate'))
sys.dont_write_bytecode = True
from baseline import otsu32, read_image


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def quantize(array, scale, dtype):
    values = np.rint(np.asarray(array, np.float64)*scale)
    limits = np.iinfo(dtype)
    if not np.isfinite(values).all() or values.min() < limits.min or values.max() > limits.max:
        raise OverflowError(f'Quantized values exceed {dtype}: {values.min()}..{values.max()}')
    return values.astype(dtype)


def prepare():
    mapping = dict(line.split() for line in (DATA/'easypr/model/province_mapping').read_text(encoding='utf8').splitlines() if line.strip())
    records, norms, legacy = [], [], []
    sources = [('binary', DATA/'characters'), ('gray', DATA/'chinese-gray/annCh')]
    for source, directory in sources:
        for path in sorted(directory.rglob('*')):
            if path.suffix.lower() not in ('.jpg', '.png', '.bmp'):
                continue
            char = mapping.get(path.parent.name, path.parent.name)
            if char not in CLASSES:
                raise ValueError(f'Unknown class {path}')
            gray = read_image(path, True)
            mask = otsu32(gray)
            if mask is None or mask.sum() < 4:
                continue
            norm = normalize(mask)
            edge = np.concatenate([mask[0], mask[-1], mask[:, 0], mask[:, -1]])
            # pHash groups exact coarse appearances; it is not an identity proof.
            low = cv2.resize(norm.astype(np.float32), (16, 16), interpolation=cv2.INTER_AREA)
            coarse = np.packbits(low > .5).tobytes()
            records.append(dict(path=path.relative_to(ROOT).as_posix(), source=source,
                class_id=CLASSES.index(char), char=char, file_sha256=sha(path.read_bytes()),
                pixels_sha256=sha(str(gray.shape).encode()+gray.tobytes()),
                normalized_sha256=sha(norm.tobytes()), coarse_sha256=sha(coarse),
                foreground_fraction=float(mask.mean()), border_fraction=float(edge.mean()),
                shape=list(gray.shape), intensity_levels=int(len(np.unique(gray)))))
            norms.append(norm); legacy.append(normalize(mask, 'legacy'))
    # Union content duplicates transitively across all labels and both sources.
    parent = list(range(len(records)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    seen = {}
    for i, row in enumerate(records):
        for field in ['file_sha256', 'pixels_sha256', 'normalized_sha256', 'coarse_sha256']:
            key = field, row[field]
            if key in seen:
                parent[find(i)] = find(seen[key])
            else:
                seen[key] = i
    groups = defaultdict(list)
    for i in range(len(records)):
        groups[find(i)].append(i)
    keep = []
    for indices in groups.values():
        labels = {records[i]['class_id'] for i in indices}
        group = min(records[i]['normalized_sha256'] for i in indices)
        bucket = int(sha(('split-v1:'+group).encode())[:8], 16) % 20
        split = 'train' if bucket < 14 else 'validation' if bucket < 17 else 'test'
        for i in indices:
            records[i].update(group=group, split=split if len(labels) == 1 else 'conflict')
        # Keep only one exact normalized image, but retain differing group images.
        unique = set()
        for i in indices:
            key = records[i]['normalized_sha256']
            if len(labels) == 1 and key not in unique:
                keep.append(i); unique.add(key)
    keep.sort()
    selected = [records[i] for i in keep]
    save(OUT/'manifest-all.json', records)
    save(OUT/'manifest.json', selected)
    np.savez_compressed(OUT/'dataset.npz', masks=np.array(norms)[keep], legacy=np.array(legacy)[keep],
        y=np.array([r['class_id'] for r in selected]), split=np.array([r['split'] for r in selected]),
        source=np.array([r['source'] for r in selected]))
    report = dict(raw_files=len(records), retained=len(keep), content_groups=len(groups),
        conflicts=sum(r['split']=='conflict' for r in records),
        counts={c:dict(Counter(r['split'] for r in selected if r['char']==c)) for c in CLASSES},
        sources={s:dict(files=sum(r['source']==s for r in records),
            median_foreground=float(np.median([r['foreground_fraction'] for r in records if r['source']==s])),
            median_border=float(np.median([r['border_fraction'] for r in records if r['source']==s]))) for s,_ in sources},
        split_boundary='Content-disjoint only. EasyPR supplies no vehicle/session identity. Unknown augmented relatives may remain.',
        provenance='https://github.com/liuruoze/EasyPR/resources/train; repository Apache-2.0; no CCPD labels used')
    save(OUT/'data-audit.json', report)
    print(json.dumps(report, ensure_ascii=True), flush=True)


def rank(scores, y):
    scores = scores.copy()
    scores[y < 31, 31:] = -1e12
    scores[y >= 31, :31] = -1e12
    order = np.argsort(-scores, axis=1, kind='stable')
    best = order[:, 0]
    top = scores[np.arange(len(y)), best]
    margin = top-scores[np.arange(len(y)), order[:, 1]]
    return best, top, margin


def metrics(y, pred, accept):
    cm = np.zeros((65,65), int)
    np.add.at(cm, (y, pred), 1)
    return dict(total=len(y), raw_correct=int((y==pred).sum()),
        correct=int(((y==pred)&accept).sum()), wrong=int(((y!=pred)&accept).sum()), rejected=int((~accept).sum()),
        confusion=cm.tolist(), per_class={c:dict(total=int((y==i).sum()), correct=int(((y==i)&(pred==i)).sum())) for i,c in enumerate(CLASSES)})


def thresholds(y, pred, top, margin):
    result = {}
    for name, group in [('province', y < 31), ('alphanumeric', y >= 31)]:
        truth, guess, score, gap = y[group], pred[group], top[group], margin[group]
        candidates = []
        for s in np.unique(np.quantile(score, np.linspace(0, .9, 19)).astype(int)):
            for m in np.unique(np.quantile(gap, np.linspace(0, .95, 39)).astype(int)):
                ok = (score >= s)&(gap >= m)
                wrong = int(((truth != guess)&ok).sum())
                correct = int(((truth == guess)&ok).sum())
                # Select 1% validation accepted-error target, maximize useful outputs.
                candidates.append(((wrong > max(0, int(ok.sum()*.01)), -correct if wrong <= int(ok.sum()*.01) else wrong, wrong), int(s), int(m)))
        _, s, m = min(candidates)
        result[name] = dict(score=s, margin=m)
    return result


def evaluate(name, scores, data, folder, weights=None):
    y, split = data['y'], data['split']
    pred, top, margin = rank(scores.astype(np.float64), y)
    val = split == 'validation'
    threshold = thresholds(y[val], pred[val], top[val], margin[val])
    accepted = np.zeros(len(y), bool)
    for key, group in [('province', y < 31), ('alphanumeric', y >= 31)]:
        accepted[group] = (top[group] >= threshold[key]['score'])&(margin[group] >= threshold[key]['margin'])
    summary = dict(name=name, thresholds=threshold, metrics={})
    for split_name in ['train', 'validation', 'test']:
        summary['metrics'][split_name] = {}
        for group_name, group in [('all', np.ones(len(y), bool)), ('province', y<31), ('alphanumeric', y>=31), ('binary', data['source']=='binary'), ('gray', data['source']=='gray')]:
            use = (split == split_name)&group
            summary['metrics'][split_name][group_name] = metrics(y[use], pred[use], accepted[use])
    folder.mkdir(exist_ok=True)
    save(folder/'summary.json', summary)
    np.savez_compressed(folder/'predictions.npz', prediction=pred, score=top, margin=margin, accepted=accepted)
    if weights:
        np.savez(folder/'weights.npz', **weights)
        bounds = {}
        for layer, max_input in [(1,32), (2,255)]:
            if 'w'+str(layer) not in weights:
                continue
            w, b = weights['w'+str(layer)].astype(np.int64), weights['b'+str(layer)].astype(np.int64)
            bound = int((max_input*np.abs(w).sum(axis=0)+np.abs(b)).max())
            bounds[str(layer)] = dict(absolute_accumulator_bound=bound, signed_bits=bound.bit_length()+1,
                                      max_abs_weight=int(np.abs(w).max()))
        interface = dict(classes=list(CLASSES), thresholds=threshold, input='32x32 row-major binary white foreground',
            model_type='mlp' if 'w2' in weights else 'linear',
            features='256 row-major 2x2 sums*8, then 32 column sums, then 32 row sums; each 0..32',
            weight_q=8, bias_q=13, hidden_q=5 if 'w2' in weights else None,
            hidden='clip((acc+128)//256,0,255)' if 'w2' in weights else None,
            score_q=13, tie='lowest class ID', bounds=bounds,
            macs=sum(v.size for k,v in weights.items() if k.startswith('w')),
            rom_bytes=sum(v.nbytes for v in weights.values()), status='offline candidate; not RTL or board validated')
        save(folder/'interface.json', interface)
        for key, array in weights.items():
            bits = 16 if key.startswith('w') else 32
            (folder/(key+'.mem')).write_text(''.join(f'{int(v)&((1<<bits)-1):0{bits//4}x}\n' for v in array.T.ravel()), encoding='ascii')
        test = np.array([np.flatnonzero((split=='test')&(y==c))[0] for c in range(65)])
        x = np.array([features(mask) for mask in data['masks'][test]])
        save(folder/'test-vectors.json', [dict(index=int(i), position=0 if y[i]<31 else 2,
            input=data['masks'][i].ravel().tolist(), features=xx.tolist(), raw_scores=ss.tolist(),
            raw_65_argmax=int(np.argmax(ss)), expected_id=int(pred[i])) for i,xx,ss in zip(test,x,integer_scores(x, weights))])
    print(name, {s:{g:{k:v for k,v in m.items() if k not in ['confusion','per_class']} for g,m in groups.items()} for s,groups in summary['metrics'].items() if s!='train'}, flush=True)
    return summary


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare','train'])
    parser.add_argument('--learn-only', action='store_true', help='Reuse dataset and existing template diagnostics')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.action == 'prepare':
        prepare(); return
    data = dict(np.load(OUT/'dataset.npz'))
    x = np.array([features(mask) for mask in data['masks']], np.float32)
    train = data['split']=='train'
    y = data['y']
    assert set(y[train]) == set(range(65))
    # Baseline medoids use training data only. No test-derived template selection.
    for name, values in ([] if args.learn_only else [('xor16', data['legacy'].reshape(-1,512)), ('grid32', x)]):
        scores = np.empty((len(y), 65), np.float32)
        template_rows = []
        for c in range(65):
            indices = np.flatnonzero(train&(y==c))
            v = values[indices].astype(np.float32)
            k = min(12, len(indices))
            km = KMeans(k, n_init=3, random_state=701).fit(v)
            centers = []
            for j in range(k):
                members = np.flatnonzero(km.labels_==j)
                pick = members[np.argmin(((v[members]-km.cluster_centers_[j])**2).sum(axis=1))]
                centers.append(v[pick]); template_rows.append(int(indices[pick]))
            score = np.full(len(y), np.inf)
            for center in centers:
                score = np.minimum(score, np.abs(values.astype(np.float32)-center).sum(axis=1))
            scores[:,c] = -score
        evaluate(name, scores, data, OUT/name)
        save(OUT/name/'training-indices.json', template_rows)
    for c in [.1, 1.]:
        svm = LinearSVC(C=c, dual=False, max_iter=5000, random_state=701).fit(x[train]/32, y[train])
        weights = dict(w1=quantize(svm.coef_.T,256,np.int16), b1=quantize(svm.intercept_,8192,np.int32))
        scores = integer_scores(x, weights)
        folder = OUT/('linear'+str(c))
        evaluate('linear'+str(c), scores, data, folder, weights)
        np.savez(folder/'float-weights.npz', w1=svm.coef_.T, b1=svm.intercept_)
        qp,_,_=rank(scores.astype(float),y); fp,_,_=rank(svm.decision_function(x/32),y)
        save(folder/'quantization.json', dict(disagreements=int((qp!=fp).sum()),
            test_disagreements=int(((qp!=fp)&(data['split']=='test')).sum()),
            float_test_correct=int(((fp==y)&(data['split']=='test')).sum()),
            range_check_before_cast=True, actual_ranges={k:[int(v.min()),int(v.max())] for k,v in weights.items()}))
    for hidden in [64,128]:
        model = MLPClassifier(hidden_layer_sizes=(hidden,), activation='relu', alpha=.01,
            batch_size=256, learning_rate_init=.001, max_iter=180, tol=1e-5,
            n_iter_no_change=15, random_state=701)
        model.fit(x[train]/32, y[train])
        weights = dict(w1=quantize(model.coefs_[0],256,np.int16), b1=quantize(model.intercepts_[0],8192,np.int32),
            w2=quantize(model.coefs_[1],256,np.int16), b2=quantize(model.intercepts_[1],8192,np.int32))
        scores = integer_scores(x, weights)
        summary = evaluate('mlp'+str(hidden), scores, data, OUT/('mlp'+str(hidden)), weights)
        np.savez(OUT/('mlp'+str(hidden))/'float-weights.npz',w1=model.coefs_[0],b1=model.intercepts_[0],w2=model.coefs_[1],b2=model.intercepts_[1])
        float_scores = np.maximum(x/32 @ model.coefs_[0]+model.intercepts_[0], 0) @ model.coefs_[1]+model.intercepts_[1]
        qp,_,_=rank(scores.astype(float),y); fp,_,_=rank(float_scores,y)
        save(OUT/('mlp'+str(hidden))/'quantization.json', dict(iterations=model.n_iter_,
            disagreements=int((qp!=fp).sum()), test_disagreements=int(((qp!=fp)&(data['split']=='test')).sum()),
            float_test_correct=int(((fp==y)&(data['split']=='test')).sum()),
            range_check_before_cast=True, actual_ranges={k:[int(v.min()),int(v.max())] for k,v in weights.items()}))


if __name__ == '__main__':
    with threadpool_limits(limits=2):
        run()
