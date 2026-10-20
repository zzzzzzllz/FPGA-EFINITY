"""Keep pre-tool inputs and audit Efinity's XML serialization separately."""
import difflib
import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
work=ROOT/'tmp/blue-plate-char-preprocess/synthesis'
provenance=work/'provenance'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
inputs=json.loads((work/'input-hashes.json').read_text())
before=provenance/'char_preprocess.before.xml'
after=provenance/'char_preprocess.after.xml'
assert sha(before)==inputs['char_preprocess.xml'],'Original XML hash differs'
for filename,digest in inputs.items():
    if filename.endswith('.xml'):continue
    assert sha(work/filename)==digest,filename
assert sha(work/'char_preprocess.v')==sha(ROOT/'tools/blue_plate/char_preprocess/rtl/char_preprocess.v')
shutil.copy2(work/'char_preprocess.xml',after)
def semantic(node):
    return node.tag,tuple(sorted(node.attrib.items())),(node.text or '').strip(),tuple(semantic(c) for c in node)
assert semantic(ET.parse(before).getroot())==semantic(ET.parse(after).getroot()),'XML semantic change'
(provenance/'xml-tool-rewrite.diff').write_text(''.join(difflib.unified_diff(before.read_text().splitlines(True),after.read_text().splitlines(True),
    fromfile='before',tofile='after')),encoding='utf8')
report_path=work/'out/char_preprocess.map.rpt'
text=report_path.read_text(errors='replace').split('Resource Summary (begin)',1)[1].split('Resource Summary (end)',1)[0]
resources={m.group(1):int(m.group(2)) for m in re.finditer(r'^(EFX_\w+)\s*:\s*(\d+)',text,re.M)}
assert resources['EFX_RAM10']>0 and resources['EFX_LUT4']>0
result=dict(resources=resources,DSP=sum(v for k,v in resources.items() if k.startswith('EFX_DSP')),
    stage='map only; no placement XLR or routed timing claim',source_sha256=inputs,
    xml_before_sha256=sha(before),xml_after_sha256=sha(after),xml_semantically_identical=True,
    original_input_manifest_unchanged=True,
    rewrite_cause='D:/Efinity/scripts/efx_run.py updates sw_version and serializes ElementTree at line 2120; sw_version is unchanged here, empty-element formatting changes.',
    map_report_sha256=sha(report_path),netlist_sha256=sha(work/'out/char_preprocess.map.v'))
(work/'synthesis-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps(result,indent=2))
