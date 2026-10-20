"""Small algorithm/integrity checks; these do not measure real-plate accuracy."""
from fractions import Fraction
import numpy as np
import baseline as b


def run():
    assert b.otsu32(np.zeros((96,320),np.uint8)) is None
    assert b.otsu32(np.full((96,320),255,np.uint8)) is None
    two=np.zeros((96,320),np.uint8);two[:,160:]=255
    assert np.array_equal(b.otsu32(two),two>0)
    rng=np.random.default_rng(9)
    for _ in range(20):
        gray=rng.integers(0,256,(96,320),dtype=np.uint8)
        bins=(gray>>3).ravel();count=len(bins);total=int(bins.sum())
        candidates=[]
        for t in range(31):
            left=bins[bins<=t];weight=len(left)
            if 0<weight<count:
                candidates.append((Fraction((int(left.sum())*count-total*weight)**2,weight*(count-weight)),-t))
        t=-max(candidates)[1]
        assert np.array_equal(b.otsu32(gray),(gray>>3)>t)
    classes=np.array(['A','A','B'])
    templates=np.zeros((3,512),np.int16);templates[1,0]=1;templates[2,:20]=1
    # Two templates of A cannot consume the runner-up category.
    mask=np.zeros((32,16),np.uint8);mask[5:27,5:11]=1
    normalized=b.normalize(mask);v=b.feature(normalized,'xor')
    templates=np.tile(v,(3,1));templates[1,0]^=1;templates[2,:20]^=1
    # classify restricts to the full alphabet, so supply all other classes far away.
    extra=[c for c in b.LETTERS if c not in 'AB']
    classes=np.array(list(classes)+extra)
    templates=np.vstack([templates,np.tile(1-v,(len(extra),1))])
    result=b.classify(mask,1,classes,templates,'xor')
    assert result['char']=='A' and result['margin']==20
    for method in ['component','projection','projection-char']:
        assert not b.segment(np.zeros((64,224,3),np.uint8),'global',method)[0]
    # A separate right rim must not join the last glyph, including a narrow 1.
    plate=np.zeros((64,224,3),np.uint8);plate[:,:,0]=90
    for x,w in [(8,23),(43,23),(78,23),(109,23),(140,23),(171,17),(195,7)]:
        plate[13:51,x:x+w]=220
    expected,_,expected_rects=b.segment(plate,'global','projection-char')
    assert len(expected)==7 and expected_rects[-1]==(195,13,7,38)
    plate[13:51,210:220]=220
    actual,_,actual_rects=b.segment(plate,'global','projection-char')
    assert actual_rects==expected_rects and all(np.array_equal(a,c) for a,c in zip(actual,expected))
    samples=b.load_samples()
    assert len({s['sha256'] for s in samples})==len(samples)
    groups={}
    for sample in samples:
        if sample['label']:
            groups.setdefault(sample['label'],set()).add(sample['split'])
    assert all(len(s)==1 for s in groups.values())
    from char_model import model
    import json
    candidate=b.ROOT/'tools/blue_plate/char_model/candidate'
    config=json.loads((candidate/'interface.json').read_text(encoding='utf8'))
    weights=dict(np.load(candidate/'weights.npz'))
    sample=samples[3]
    plate=b.warp(b.read_image(b.ROOT/sample['path']),np.array(sample['points'])[[2,3,0,1]])
    chars,_,_=b.segment(plate,'global','projection-char')
    result,_,_=b.recognize(plate,'global',None,None,'xor','projection-char',(weights,config['thresholds']))
    assert len(chars)==7
    assert result['scores']==[model.predict(char,i,candidate) for i,char in enumerate(chars)]
    print('PASS: exact Otsu, uniform rejection, distinct-class margin, blank segmentation, hash/identity splits')
    print('PASS: integrated integer classifier matches public predict API on seven original ROIs; normalized once')
    print('PASS: separate right border removed while preserving a narrow final 1')
    print('Synthetic check inputs are not license-plate accuracy samples.')


if __name__=='__main__':run()
