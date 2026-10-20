"""Verify mapping provenance and report physical primitive counts, not timing closure."""
from pathlib import Path
import hashlib,json,re,xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/mac8/synthesis'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
original=json.loads((OUT/'input-hashes.json').read_text())
assert sha(OUT/'mac8.before.xml')==original['mac8.xml']
for name in ('mac8.v','mac8.sdc'):assert sha(OUT/name)==original[name]
assert sha(OUT/'mac8.v')==sha(HERE/'rtl/mac8.v')
def semantic(n):
    return n.tag,sorted(n.attrib.items()),(n.text or '').strip(),[semantic(c) for c in n]
assert semantic(ET.parse(OUT/'mac8.before.xml').getroot())==semantic(ET.parse(OUT/'mac8.xml').getroot())
report=OUT/'out/mac8.map.rpt';netlist=OUT/'out/mac8.map.v'
section=report.read_text().split('Resource Summary (begin)',1)[1].split('Resource Summary (end)',1)[0]
resources={m[1]:int(m[2]) for m in re.finditer(r'^(EFX_\w+)\s*:\s*(\d+)',section,re.M)}
assert resources['EFX_DSP48']==8
assert not any('RAM' in key and value for key,value in resources.items())
assert not re.search(r'^\s*EFX_RAM\w*\s',netlist.read_text(),re.M)
assert re.search(r'map\s*:\s*PASS',(OUT/'map.console.log').read_text())
assert '-period 10.000' in (OUT/'mac8.sdc').read_text()
result={'exit_code':0,'resources':resources,'RAM10':0,'clock_constraint_ns':10.0,
    'timing_status':'SDC supplied; map-only flow produced no placed/routed STA or Fmax. 100MHz is not verified.',
    'xml_semantically_identical':True,'source_copy_matches':True,
    'files_sha256':{str(p):sha(p) for p in [HERE/'rtl/mac8.v',OUT/'mac8.sdc',OUT/'mac8.before.xml',OUT/'mac8.xml',report,netlist,OUT/'map.console.log']},
    'historical_log_note':'Efinity appends err/warn logs across runs. First failed CLK-port check is preserved separately in ../first-map-error; current map.console.log and map.rpt are the successful run.'}
(OUT/'synthesis-summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
