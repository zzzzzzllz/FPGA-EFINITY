"""Development-only ROI audit and frozen-model scoring, separate from corpus test."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import cv2
import numpy as np
from model import CLASSES, features, normalize, integer_scores, allowed_ids
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'tools/blue_plate'))
sys.dont_write_bytecode = True
import baseline as b
OUT = ROOT/'tmp/blue-plate-char-model'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['prepare', 'score'])
    p.add_argument('--model', default='mlp128')
    p.add_argument('--audited', default='')
    args = p.parse_args()
    if args.action == 'prepare':
        records, masks, strips = [], [], []
        for index, sample in enumerate(b.load_samples()):
            if sample['split'] != 'development' or not sample['label']:
                continue
            plate = b.warp(b.read_image(ROOT/sample['path']), np.array(sample['points'])[[2,3,0,1]])
            chars, mask, rects = b.segment(plate, 'global', 'projection')
            if len(chars) != 7:
                continue
            records.append(dict(index=index, path=sample['path'], label=sample['label'], rects=rects,
                source_sha256=sample['sha256']))
            masks.extend(normalize(char) for char in chars)
            strip = np.hstack([np.pad(cv2.resize(char*255, (48,64), interpolation=cv2.INTER_NEAREST), ((0,0),(2,2))) for char in chars])
            header = np.zeros((18,strip.shape[1]), np.uint8)
            cv2.putText(header, str(index), (2,13), 0, .4, 255, 1)
            strips.append(np.vstack([header,strip]))
        for start in range(0,len(strips),12):
            cv2.imwrite(str(OUT/f'roi-contact-{start//12}.png'), np.vstack(strips[start:start+12]))
        np.save(OUT/'roi-masks.npy', np.array(masks))
        (OUT/'roi-records.json').write_text(json.dumps(dict(baseline_sha256=hashlib.sha256((ROOT/'tools/blue_plate/baseline.py').read_bytes()).hexdigest(), records=records), ensure_ascii=False, indent=2), encoding='utf8')
        print([(r['index'],r['label']) for r in records])
    else:
        audited = set(map(int, args.audited.split(',')))
        records = json.loads((OUT/'roi-records.json').read_text(encoding='utf8'))['records']
        masks = np.load(OUT/'roi-masks.npy').reshape(-1,7,32,32)
        folder = OUT/args.model
        config = json.loads((folder/'interface.json').read_text(encoding='utf8'))
        weights = dict(np.load(folder/'weights.npz'))
        result=[]
        for r, chars in zip(records,masks):
            if r['index'] not in audited:
                continue
            predicted=[]; decisions=[]
            for position, mask in enumerate(chars):
                score = integer_scores(features(mask), weights)
                ids = allowed_ids(position)
                ranked = ids[np.argsort(-score[ids], kind='stable')]
                best, second = ranked[:2]
                threshold = config['thresholds']['province' if position==0 else 'alphanumeric']
                predicted.append(CLASSES[best])
                decisions.append(bool(score[best]>=threshold['score'] and score[best]-score[second]>=threshold['margin']))
            result.append(dict(**r, prediction=''.join(predicted), accepted=all(decisions), char_accepted=decisions))
        summary=dict(plates=len(result), characters=len(result)*7, correct_characters=sum(sum(a==b for a,b in zip(r['label'],r['prediction'])) for r in result),
            raw_correct=sum(r['label']==r['prediction'] for r in result), correct=sum(r['accepted'] and r['label']==r['prediction'] for r in result),
            wrong=sum(r['accepted'] and r['label']!=r['prediction'] for r in result), reject=sum(not r['accepted'] for r in result),
            warning='Visually selected development oracle ROIs. Not automatic localization or heldout plate accuracy.', rows=result)
        (folder/'roi-diagnostic.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False))


if __name__ == '__main__': main()
