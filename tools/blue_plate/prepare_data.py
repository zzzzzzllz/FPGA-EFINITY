"""Download pinned research inputs; never execute downloaded code."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'tmp/blue-plate-g1'
EASYPR = 'a0a9f3c3f612e7c8d9046bd9c5770249cfb86850'
SAMPLE = '7a61f4ea777da73c96e125ddd72d063b77219b1a'
CCPD = '02aaea15137c4d2fe662e57d257c6822356e9304'


def download(item):
    repo, commit, remote, local = item
    url = f'https://raw.githubusercontent.com/{repo}/{commit}/' + urllib.parse.quote(remote)
    path = OUT / local
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            path.write_bytes(response.read())
    data = path.read_bytes()
    return dict(url=url, path=path.relative_to(ROOT).as_posix(), bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tree_url = f'https://api.github.com/repos/1gubigu/ccpd/git/trees/{SAMPLE}?recursive=1'
    with urllib.request.urlopen(tree_url, timeout=60) as response:
        tree = json.load(response)
    items = [('1gubigu/ccpd', SAMPLE, x['path'], 'images/' + x['path'])
             for x in tree['tree'] if x['path'].lower().endswith('.jpg')]
    for remote in ['LICENSE', 'README.md', 'resources/train/ann.7z',
                   'resources/train/annCh.7z', 'model/province_mapping',
                   'model/ann.xml', 'model/ann_chinese.xml',
                   'src/train/ann_train.cpp', 'src/train/annCh_train.cpp']:
        items.append(('liuruoze/EasyPR', EASYPR, remote, 'easypr/' + remote))
    # The upstream dataset license is independent of the subset mirror.
    for remote in ['LICENSE', 'README.md', 'rpnet/load_data.py']:
        items.append(('detectRecog/CCPD', CCPD, remote, 'ccpd/' + remote))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(download, items))
    (OUT / 'sources.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    for archive, destination in [('ann.7z', 'characters'), ('annCh.7z', 'chinese-gray')]:
        source = OUT / 'easypr/resources/train' / archive
        target = OUT / destination
        target.mkdir(exist_ok=True)
        entries = subprocess.check_output(['tar', '-tf', str(source)], text=True).splitlines()
        for entry in entries:
            if not (target / entry).resolve().is_relative_to(target.resolve()):
                raise ValueError(f'Archive entry escapes destination: {entry}')
        subprocess.run(['tar', '-xf', str(source), '-C', str(target)], check=True)
    print(f'Downloaded/verified {len(records)} inputs in {OUT}')


if __name__ == '__main__':
    main()
