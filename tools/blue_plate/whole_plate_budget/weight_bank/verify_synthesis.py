"""Confirm all sixteen physical RAM instances and the unchanged arithmetic core."""
from pathlib import Path
import hashlib,json,re,xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/weight-bank/synthesis'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((OUT/'input-hashes.json').read_text())
for name,digest in manifest.items():
    path=OUT/('weight_mac8.before.xml' if name.endswith('.xml') else name)
    assert sha(path)==digest,name
for name in ('weight_bank8.v','weight_mac8.v'):assert sha(OUT/name)==sha(HERE/'rtl'/name)
assert sha(OUT/'mac8.v')==sha(HERE.parent/'mac8/rtl/mac8.v')=='f3490692d9bd2160144da3c92693bb8b65f0cbe0a9d435dc4321514cd2c7ffee'
def semantic(n):return n.tag,sorted(n.attrib.items()),(n.text or '').strip(),[semantic(c) for c in n]
assert semantic(ET.parse(OUT/'weight_mac8.before.xml').getroot())==semantic(ET.parse(OUT/'weight_mac8.xml').getroot())
report=OUT/'out/weight_mac8.map.rpt';netlist=OUT/'out/weight_mac8.map.v'
section=report.read_text().split('Resource Summary (begin)',1)[1].split('Resource Summary (end)',1)[0]
resources={m[1]:int(m[2]) for m in re.finditer(r'^(EFX_\w+)\s*:\s*(\d+)',section,re.M)}
assert resources['EFX_DSP48']==8 and resources['EFX_RAM10']==16
text=netlist.read_text();cells=re.findall(r'^\s*EFX_RAM10\s+(\S+)\s+\(',text,re.M)
assert len(cells)==16 and len(set(cells))==16
params={}
for cell in cells:
    values=dict(re.findall(r'defparam\s+'+re.escape(cell)+r'\s+\.(\w+)\s*=\s*([^;]+);',text))
    expected={'READ_WIDTH':'16','WRITE_WIDTH':'16','OUTPUT_REG':"1'b0",'WRITE_MODE':'"READ_UNKNOWN"','RESET_RAM':'"SYNC"'}
    assert all(values.get(k)==v for k,v in expected.items()),cell
    params[cell]=expected
assert re.search(r'map\s*:\s*PASS',(OUT/'map.console.log').read_text())
assert '-period 10.000' in (OUT/'weight_mac8.sdc').read_text()
paths=[OUT/name for name in manifest if not name.endswith('.xml')]+[OUT/'weight_mac8.before.xml',OUT/'weight_mac8.xml',report,netlist,OUT/'map.console.log']
result={'exit_code':0,'resources':resources,'physical_RAM_instances':params,
    'effective_weight_bytes':2048*64//8,'source_copies_and_MAC_hash_verified':True,
    'xml_semantically_identical':True,'clock_constraint_ns':10.0,
    'timing_status':'Map only. SDC provided; no placed/routed STA or verified 100MHz.',
    'files_sha256':{str(p):sha(p) for p in paths}}
(OUT/'synthesis-summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('physical_RAM_instances','files_sha256')},indent=2))
