"""Preselect new CCPD photographs by geometry, before recognition is run."""
import concurrent.futures
import hashlib
import json
import math
from pathlib import Path
import urllib.parse
import urllib.request
import urllib.error

import cv2
import numpy as np
import baseline as b

REPO='libohhhhhhhh/-yolo_ccpd_10k-'
REVISION='e0f688cda0fb89b2679fc746ed24086b763f6c07'
OUT=b.ROOT/'tmp/blue-plate-normal-g1'


def main():
    OUT.mkdir(exist_ok=True)
    tree=json.loads((b.DATA/'more-data-research/liboh-tree.json').read_text(encoding='utf8'))
    assert tree['sha']==REVISION
    old={Path(s['path']).stem.split('-')[4] for s in b.load_samples() if s['label']}
    eligible=[]
    for entry in tree['tree']:
        path=Path(entry['path']);parts=path.stem.split('-')
        if path.suffix.lower()!='.jpg' or len(parts)!=7 or parts[4] in old:
            continue
        ids=[int(n) for n in parts[4].split('_')]
        if len(ids)!=7 or ids[0]>=31 or ids[1]>=24 or max(ids[2:])>=34:
            continue
        br,bl,tl,tr=[[int(n) for n in point.split('&')] for point in parts[3].split('_')]
        scale=720/1160
        width=(math.dist(tr,tl)+math.dist(br,bl))/2*scale
        height=(math.dist(bl,tl)+math.dist(br,tr))/2*scale
        roll=max(abs(math.degrees(math.atan2(tr[1]-tl[1],tr[0]-tl[0]))),abs(math.degrees(math.atan2(br[1]-bl[1],br[0]-bl[0]))))
        # Width/roll come from the existing design. Plate height >=50 is a
        # declared proxy for 32px characters, not an assertion of readability.
        if 160<=width<=300 and 50<=height<=96 and roll<=5:
            eligible.append(dict(path=entry['path'],git_blob=entry['sha'],identity=parts[4],
                                 width720=width,height720=height,roll=roll))
    eligible.sort(key=lambda x:hashlib.sha256(x['path'].encode()).hexdigest())
    unique={}
    for entry in eligible:
        unique.setdefault(entry['identity'],entry)
    selected=list(unique.values())[:500]
    plan=dict(repo=REPO,revision=REVISION,eligible_images=len(eligible),eligible_identities=len(unique),
              selected=len(selected),rules=dict(width720=[160,300],plate_height720=[50,96],max_abs_roll=5,
              assumed_source_size=[720,1160],exclude_old_identities=True,selection='SHA256(path) order; one per identity'),
              recognition_not_used=True,session_metadata='unknown',records=selected)
    # This plan exists on disk before the first selected image is downloaded.
    (OUT/'selection-before-recognition.json').write_text(json.dumps(plan,indent=2),encoding='utf8')
    print(f'Selected {len(selected)} of {len(unique)} eligible identities',flush=True)
    def download(entry):
        path=OUT/'images/ccpd_10k'/Path(entry['path']).name;path.parent.mkdir(parents=True,exist_ok=True)
        url=f'https://raw.githubusercontent.com/{REPO}/{REVISION}/'+urllib.parse.quote(entry['path'],safe='/&')
        transport_url=None
        if path.exists():
            data=path.read_bytes()
        else:
            failures=[]
            for attempt in range(3):
                transport_url=url if attempt!=1 else f'https://raw.githubusercontent.com/{REPO}/master/'+urllib.parse.quote(entry['path'],safe='/&')
                try:
                    with urllib.request.urlopen(transport_url,timeout=8) as response:data=response.read()
                    break
                except (urllib.error.URLError,TimeoutError,ConnectionError) as error:
                    failures.append(dict(url=transport_url,error=f'{type(error).__name__}: {error}'))
            else:
                return dict(url=url,failed=True,attempt_errors=failures)
        actual_blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if actual_blob!=entry['git_blob']:
            raise ValueError(f'Download differs from selected Git blob: {path}')
        image=cv2.imdecode(np.frombuffer(data,np.uint8),1)
        if image is None or image.shape[:2]!=(1160,720):
            raise ValueError(f'Source dimensions invalidate preselection: {path}')
        path.write_bytes(data)
        return dict(url=url,transport_url=transport_url,path=path.relative_to(b.ROOT).as_posix(),sha256=hashlib.sha256(data).hexdigest(),
                    bytes=len(data),source_size=[720,1160])
    records=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(download,entry) for entry in selected]
        for future in concurrent.futures.as_completed(futures):
            record=future.result();records.append(record)
            with (OUT/'download-progress.jsonl').open('a',encoding='utf8') as log:
                log.write(json.dumps(record)+'\n')
            if len(records)%50==0:print(f'Processed {len(records)}/{len(selected)}',flush=True)
    failed=[r for r in records if r.get('failed')]
    (OUT/'download-failures.json').write_text(json.dumps(failed,indent=2),encoding='utf8')
    records=[r for r in records if not r.get('failed')]
    (OUT/'sources.json').write_text(json.dumps(sorted(records,key=lambda r:r['path']),indent=2),encoding='utf8')
    for name in ['LICENSE','README.md']:
        (OUT/('CCPD-'+name)).write_bytes((b.DATA/'ccpd'/name).read_bytes())
    print(f'Complete: {len(records)} real images, 0 generated plates',flush=True)
    if failed:
        raise RuntimeError(f'{len(failed)} selected downloads failed; retained their URLs, did not substitute samples')


if __name__=='__main__':main()
