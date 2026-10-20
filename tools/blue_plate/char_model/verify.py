"""Check ROM layout, scalar integer arithmetic, bounds, and position decisions."""
import argparse
import json
from pathlib import Path
import numpy as np
from model import CLASSES, features, integer_scores, normalize, decide

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'tmp/blue-plate-char-model'


def scalar_scores(x, weights):
    def layer(inputs, w, b):
        return [int(b[j])+sum(int(a)*int(w[i,j]) for i,a in enumerate(inputs)) for j in range(w.shape[1])]
    first = layer(x, weights['w1'], weights['b1'])
    if 'w2' not in weights:
        return first
    hidden = [min(255,max(0,(v+128)//256)) for v in first]
    return layer(hidden, weights['w2'], weights['b2'])


def main():
    p = argparse.ArgumentParser(); p.add_argument('--model', default='mlp128')
    p.add_argument('--candidate', type=Path, help='Check exported fixtures without training data')
    args=p.parse_args()
    if args.candidate:
        folder=args.candidate
        config=json.loads((folder/'interface.json').read_text(encoding='utf8'))
        weights=dict(np.load(folder/'weights.npz'))
        for key,array in weights.items():
            for bits,suffix in ([(16,'.mem'),(10,'-s10.mem')] if key.startswith('w') else [(32,'.mem')]):
                values=[int(v,16) for v in (folder/(key+suffix)).read_text().splitlines()]
                decoded=[v-(1<<bits) if v&(1<<(bits-1)) else v for v in values]
                assert np.array_equal(decoded,array.T.ravel()), key+suffix
            if key.startswith('w'):
                values=[int(v,2) for v in (folder/(key+'-s10.bin')).read_text().splitlines()]
                assert np.array_equal([v-1024 if v&512 else v for v in values],array.T.ravel())
        vectors=json.loads((folder/'test-vectors.json').read_text(encoding='utf8'))
        for v in vectors:
            if v['kind']=='tie-score-bus':
                scores=np.array(v['raw_scores'],np.int64)
            else:
                x=features(np.array(v['input']).reshape(32,32))
                assert x.tolist()==v['features']
                scores=integer_scores(x,weights)
                assert scores.tolist()==v['raw_scores']==scalar_scores(x,weights)
            assert decide(scores,v['position'],config['thresholds'])==v['expected']
        print(json.dumps(dict(candidate=str(folder),vectors=len(vectors),exact=True)))
        return
    folder = OUT/args.model
    data = np.load(OUT/'dataset.npz')
    config = json.loads((folder/'interface.json').read_text(encoding='utf8'))
    weights = dict(np.load(folder/'weights.npz'))
    for key,array in weights.items():
        bits=16 if key.startswith('w') else 32
        raw=[int(v,16) for v in (folder/(key+'.mem')).read_text().splitlines()]
        signed=np.array([v-(1<<bits) if v&(1<<(bits-1)) else v for v in raw])
        assert np.array_equal(signed,array.T.ravel()), key
        if key.startswith('w'):
            if array.min() < -512 or array.max() > 511:
                raise OverflowError('Weights do not fit signed 10-bit ROM')
            packed=''.join(f'{int(v)&1023:03x}\n' for v in array.T.ravel())
            (folder/(key+'-s10.mem')).write_text(packed,encoding='ascii')
            (folder/(key+'-s10.bin')).write_text(''.join(f'{int(v)&1023:010b}\n' for v in array.T.ravel()),encoding='ascii')
            restored=np.array([int(v,16)-1024 if int(v,16)&512 else int(v,16) for v in packed.splitlines()])
            assert np.array_equal(restored,array.T.ravel())
    vectors=[]
    for class_id in range(65):
        indices=np.flatnonzero((data['split']=='test')&(data['y']==class_id))
        if not len(indices):
            raise AssertionError(f'No test sample for {CLASSES[class_id]}')
        i=int(indices[0]); mask=data['masks'][i]; x=features(mask)
        scores=integer_scores(x,weights)
        assert scalar_scores(x,weights)==scores.tolist()
        positions=[0] if class_id<31 else [1,2] if class_id<55 else [2]
        for position in positions:
            vectors.append(dict(kind='real-corpus',dataset_index=i,truth_id=class_id,position=position,
                input=mask.ravel().tolist(),features=x.tolist(),raw_scores=scores.tolist(),
                raw_65_argmax=int(np.argmax(scores)),expected=decide(scores,position,config['thresholds'])))
    predictions=np.load(folder/'predictions.npz')
    for i in np.flatnonzero((data['split']=='test')&(~predictions['accepted']))[:10]:
        mask=data['masks'][i]; x=features(mask); scores=integer_scores(x,weights)
        position=0 if data['y'][i]<31 else 2
        decision=decide(scores,position,config['thresholds'])
        assert not decision['accepted']
        vectors.append(dict(kind='rejection',dataset_index=int(i),truth_id=int(data['y'][i]),position=position,
            input=mask.ravel().tolist(),features=x.tolist(),raw_scores=scores.tolist(),
            raw_65_argmax=int(np.argmax(scores)),expected=decision))
    # A tied score bus verifies deterministic selection independently of the MACs.
    for position,expected_id in [(0,0),(1,31),(2,31)]:
        score=np.zeros(65,np.int64)
        result=decide(score,position,config['thresholds'])
        assert result['id']==expected_id and result['margin']==0
        vectors.append(dict(kind='tie-score-bus',position=position,raw_scores=score.tolist(),expected=result))
    rng=np.random.default_rng(701)
    adversarial=np.vstack([np.zeros(320,int),np.full(320,32,int),rng.integers(0,33,(30,320))])
    for x in adversarial:
        assert scalar_scores(x,weights)==integer_scores(x,weights).tolist()
    for invalid in [np.zeros((32,32),np.uint8), np.full((32,32),2,np.uint8)]:
        try: normalize(invalid)
        except ValueError: pass
        else: raise AssertionError('Invalid input accepted')
    # Identity normalization is not assumed: feature extraction consumes canonical masks directly.
    (folder/'test-vectors.json').write_text(json.dumps(vectors,ensure_ascii=False,indent=2),encoding='utf8')
    result=dict(model=args.model,rom_layout='destination-major, then source; signed hex',
        classes_covered=65,positions_covered=[0,1,2],real_vectors=sum(v['kind']=='real-corpus' for v in vectors),
        rejection_vectors=sum(v['kind']=='rejection' for v in vectors),tie_vectors=3,adversarial_mac_vectors=len(adversarial),
        scalar_numpy_exact=True,rom_roundtrip_exact=True,invalid_inputs_rejected=True)
    (folder/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result))


if __name__=='__main__': main()
