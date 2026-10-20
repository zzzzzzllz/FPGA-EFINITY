"""Verify the selected release, relocated build inputs and optional fresh build."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(project, runtime=False, build_dir=None):
    project=project.resolve()
    repo=project.parents[1]
    manifest=json.loads((project/'release/manifest.json').read_text(encoding='utf-8'))
    bit=project/'release/ti60f225_oob.bit'
    if sha(bit)!=manifest['bitstream_sha256']:
        raise ValueError(f'Release bitstream hash mismatch: {bit}')
    for rel,digest in manifest['runtime_sha256'].items():
        if sha(project/rel)!=digest:
            raise ValueError(f'Runtime config hash mismatch: {rel}')
    result={'version':project.name,'build_id':manifest['build_id'],'release_sha256':sha(bit),'runtime':'PASS'}
    if not runtime:
        count=0
        for entry in manifest['source_files']:
            rel=entry['path'].replace('\\','/')
            # Documents and vendor simulator output were separated from build inputs.
            if Path(rel).suffix.lower() in ('.docx','.pdf','.txt','.wlf'):
                continue
            path=project/('tests/'+rel if rel.startswith('tb_') else rel)
            expected=entry.get('relocated_sha256',entry['sha256']) if rel.startswith('tb_') else entry['sha256']
            if sha(path)!=expected:
                raise ValueError(f'Frozen input changed: {path}')
            count+=1
        ns={'e':'http://www.efinixinc.com/enf_proj'}
        xml=ET.parse(project/'ti60f225_oob.xml')
        inputs=[]
        for tag in ('design_file','peri_file','sdc_file'):
            for node in xml.findall('.//e:'+tag,ns):
                path=project/node.attrib['name']
                if not path.is_file(): raise FileNotFoundError(path)
                inputs.append(path)
        for path in inputs:
            if path.suffix.lower() not in ('.v','.sv','.vh','.svh'): continue
            text=path.read_text(encoding='utf-8',errors='replace')
            text=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
            for name in re.findall(r'`include\s+"([^"]+)"',text):
                if not ((path.parent/name).is_file() or (project/name).is_file() or list(project.rglob(name))):
                    raise FileNotFoundError(f'{path}: include {name}')
        for path in project.rglob('*.py'):
            ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path))
        for entry in ('build.cmd','load.cmd','control.cmd','control.py','test.cmd'):
            if not (project/entry).is_file(): raise FileNotFoundError(project/entry)
        result.update(source_hashes=count,xml_inputs=len(inputs),source='PASS',python_syntax='PASS')
    if build_dir:
        out=build_dir.resolve()/'outflow'
        log=(out/'ti60f225_oob.log').read_text(errors='replace')
        for stage in ('map','pnr','pgm'):
            if f'Stage completed: {stage}' not in log: raise ValueError(f'Incomplete build: {stage}')
        if not any(f'Stage completed: {x}' in log for x in ('pt','interface')): raise ValueError('Missing interface build')
        timing=(out/'ti60f225_oob.timing.rpt').read_text(errors='replace')
        setup=timing.split('Setup (Max) Clock Relationship',1)[1].split('Hold (Min)',1)[0]
        hold=timing.split('Hold (Min) Clock Relationship',1)[1].split('NOTE:',1)[0]
        slacks=[]
        for section in (setup,hold):
            values=[float(m.group(1)) for m in re.finditer(r'^\S+\s+\S+\s+[\d.]+\s+(-?[\d.]+)\s+\(',section,re.M)]
            if not values or min(values)<0: raise ValueError('Timing did not pass')
            slacks.append(min(values))
        result.update(build='PASS',timing_min_slack_ns=slacks,built_bitstream_sha256=sha(out/'ti60f225_oob.bit'))
        place=(out/'ti60f225_oob.place.rpt').read_text(errors='replace')
        resources={}
        for label in ('XLRs','Memory Blocks','DSP Blocks'):
            match=re.search(r'^'+label+r':\s*(\d+)\s*/\s*(\d+)',place,re.M)
            if not match: raise ValueError(f'Missing resource result: {label}')
            used,total=map(int,match.groups())
            headroom=manifest.get('resource_headroom_percent',{}).get(label,20)
            if not 0<headroom<100: raise ValueError(f'Invalid resource headroom: {label}')
            if used>total*(1-headroom/100): raise ValueError(f'Resource headroom below {headroom}%: {label}')
            resources[label]={'used':used,'total':total,'minimum_headroom_percent':headroom}
        result['resources']=resources
        (build_dir/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project',type=Path)
    parser.add_argument('--runtime',action='store_true')
    parser.add_argument('--build-dir',type=Path)
    args=parser.parse_args()
    print(json.dumps(verify(args.project,args.runtime,args.build_dir),indent=2))
