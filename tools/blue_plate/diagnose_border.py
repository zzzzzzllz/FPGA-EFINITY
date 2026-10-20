"""Compare frozen development failures before/after right-rim cleanup."""
import hashlib
import json
from pathlib import Path
import cv2
import baseline as b


def main():
    root=b.ROOT/'tmp/blue-plate-normal-g1'
    frozen=root/'frozen-development-rois'
    manifest=json.loads((frozen/'manifest.json').read_text(encoding='utf8'))
    before=json.loads((root/'partial-standard/results.json').read_text(encoding='utf8'))
    after=json.loads((root/'border-standard/results.json').read_text(encoding='utf8'))
    after_map={(r['path'],r['mode']):r for r in after}
    records=[]
    for record in manifest['records']:
        if not record['accepted_wrong']:continue
        path=record['source'];mode=record['mode']
        updated=after_map[path,mode]
        plate=b.read_image(b.ROOT/record['folder']/'plate.png')
        chars,mask,rects=b.segment(plate,'global','projection-char')
        folder=frozen/(Path(record['folder']).name+'-after-border');folder.mkdir(exist_ok=True)
        cv2.imwrite(str(folder/'geometry-mask.png'),mask*255)
        for pos,char in enumerate(chars):cv2.imwrite(str(folder/f'char-{pos}-binary.png'),char*255)
        changed=[i for i,(old,new) in enumerate(zip(record['characters'],rects)) if old['rect']!=list(new)]
        records.append(dict(source=path,mode=mode,label=record['label'],before=record['result'],
            after=updated['result'],changed_rect_positions=changed,
            after_rects=rects,after_folder=folder.relative_to(b.ROOT).as_posix(),
            outcome='correct' if updated['result']['raw']==record['label'] and b.accepted(updated['result'],0,0)
            else 'wrong' if b.accepted(updated['result'],0,0) else 'rejected'))
    regressions=[]
    for old in before:
        new=after_map[old['path'],old['mode']]
        if old['result']['raw']==old['label'] and b.accepted(old['result'],0,0) and (new['result']['raw']!=new['label'] or not b.accepted(new['result'],0,0)):
            regressions.append(dict(source=old['path'],mode=old['mode'],split=old['split'],before=old['result'],after=new['result']))
    payload=dict(heldout_consumed=0,baseline_sha256=hashlib.sha256(Path(b.__file__).read_bytes()).hexdigest(),
                 cases=records,previously_accepted_correct_regressions=regressions)
    (root/'border-diagnosis.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    for record in records:print(record['mode'],record['label'],record['before']['raw'],'->',record['after']['raw'],record['outcome'],record['changed_rect_positions'])
    print('Previously accepted-correct regressions:',len(regressions))


if __name__=='__main__':main()
