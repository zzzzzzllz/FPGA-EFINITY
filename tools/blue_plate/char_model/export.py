"""Freeze the smaller linear integration candidate and concise audit tables."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import shutil
from model import CLASSES

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'tmp/blue-plate-char-model'
DOC=ROOT/'docs/validation/blue-plate/char-model'
DEST=Path(__file__).resolve().parent/'candidate'


def load(path): return json.loads(path.read_text(encoding='utf8'))
def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def main():
    selected='linear0.1'; source=OUT/selected
    DEST.mkdir(exist_ok=True); DOC.mkdir(exist_ok=True)
    for name in ['weights.npz','w1.mem','w1-s10.mem','w1-s10.bin','b1.mem','test-vectors.json','quantization.json','verification.json']:
        shutil.copy2(source/name,DEST/name)
    interface=load(source/'interface.json')
    interface.update(model_type='linear',hidden=None,hidden_q=None,
        selection='Linear C=0.1 chosen on validation; MLP128 has equal 15-plate development ROI accepted/wrong/reject counts at higher ROM cost.',
        status='integration evaluation candidate; not approved for reliable plate output',
        normalization='Tight bbox; aspect fit in 28x28; half-up integer dimensions; center floor in32x32; source coordinates floor(dest*source_size/dest_size).',
        input_boundary='predict takes raw cropped mask and normalizes once; test-vector input is canonical and goes directly to features, never predict. Normalization is not idempotent.',
        rom_layout='destination-major: address=class_id*320+feature_id; w1-s10.mem signed10, b1.mem signed32',
        accumulation='signed32 recommended; all legal feature vectors bounded by +/-349142; no clipping or activation',
        strict_operating_point=load(OUT/'confidence.json')[selected]['validation_zero_errors']['thresholds'])
    save(DEST/'interface.json',interface)
    manifest=load(OUT/'manifest.json')
    summary={}
    for name in ['xor16','grid32','linear0.1','linear1.0','mlp64','mlp128']:
        original=load(OUT/name/'summary.json')
        compact={split:{group:{k:v for k,v in m.items() if k not in ['confusion','per_class']} for group,m in groups.items()} for split,groups in original['metrics'].items()}
        summary[name]=compact
        if name.startswith(('linear','mlp')):
            with (DOC/(name+'-classes.csv')).open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.writer(f); w.writerow(['id','char','train','validation','test','test_raw_correct'])
                for i,c in enumerate(CLASSES):
                    counts=Counter(r['split'] for r in manifest if r['class_id']==i)
                    w.writerow([i,c,counts['train'],counts['validation'],counts['test'],original['metrics']['test']['all']['per_class'][c]['correct']])
            with (DOC/(name+'-confusion.csv')).open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.writer(f);w.writerow(['truth/prediction',*CLASSES])
                for c,row in zip(CLASSES,original['metrics']['test']['all']['confusion']):w.writerow([c,*row])
    save(DOC/'comparison.json',summary)
    for name in ['data-audit.json','confidence.json','roi-records.json']:
        shutil.copy2(OUT/name,DOC/name)
    for name in ['linear0.1','mlp64','mlp128']:
        shutil.copy2(OUT/name/'roi-diagnostic.json',DOC/(name+'-roi.json'))
    hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in list(DEST.glob('*'))+[OUT/'manifest-all.json',OUT/'manifest.json',OUT/'dataset.npz']}
    save(DOC/'artifact-hashes.json',hashes)
    print(json.dumps(dict(selected=selected,export=str(DEST),files=len(list(DEST.glob('*'))))))


if __name__=='__main__':main()
