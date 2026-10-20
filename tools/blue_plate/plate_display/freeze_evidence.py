"""Freeze final simulation/map evidence and verify the mapped source snapshots."""
import hashlib
import json
from pathlib import Path
import re
import shutil

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OUT=ROOT/'tmp/blue-plate-plate-display';DOC=ROOT/'docs/validation/blue-plate/plate-display'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    sim=json.loads((OUT/'verification.json').read_text(encoding='utf8'))
    for name,h in sim['sources_sha256'].items():assert sha(HERE/name)==h,name
    reports={}
    for top in ['plate_osd','plate_display']:
        directory=OUT/'synthesis'/top
        for p in directory.glob('*.v'):
            expected=(HERE/p.name).read_text().replace('tools/blue_plate/plate_display/plate_font.mem','plate_font.mem')
            assert p.read_text()==expected,p
        for name in ['plate_defs.vh','plate_font.mem']:assert sha(directory/name)==sha(HERE/name)
        report=directory/'out'/(top+'.map.rpt')
        assert report.stat().st_mtime>=max(p.stat().st_mtime for p in directory.glob('*.v'))
        content=report.read_text()
        resources={name:int(value) for name,value in re.findall(r'^(EFX_\w+)\s+:\s+(\d+)',content,re.M)}
        assert resources['EFX_RAM10']==16
        assert len(re.findall(r'\tEFX_RAM10: .*font',content))==16
        reports[top]=dict(resources=resources,map_report_sha256=sha(report),mapped_netlist_sha256=sha(directory/'out'/(top+'.map.v')),
            project_snapshot_sha256=sha(directory/'source-hashes.json'),scope='map only; no PNR or board test')
        shutil.copy2(report,DOC/(top+'.map.rpt'))
        shutil.copy2(directory/'out'/(top+'.res.csv'),DOC/(top+'.res.csv'))
    review_path=ROOT/'tmp/blue-plate-review/plate-display/review-result.json'
    review=json.loads(review_path.read_text(encoding='utf8'))
    changed=[n for n,h in review['source_hashes'].items() if sha(HERE/n)!=h]
    shutil.copy2(review_path,DOC/'independent-review.json')
    result=dict(sources_sha256={p.name:sha(p) for p in HERE.iterdir() if p.is_file()},synthesis=reports,
        simulation_sha256=sha(OUT/'verification.json'),state_checks_per_clock_ratio=64,clock_periods_ns=[[10,6],[10,14],[10,22]],
        pixels=sim['rendered_pixels'],pixel_mismatches=sim['pixel_mismatches'],rendered_class_count=sim['rendered_class_count'],
        independent_review_source_differences=changed,independent_review_note='Final OSD uses explicit expression widths; local OSD test now exercises all 65 classes in valid seven-character layouts. State RTL is unchanged from independent review.',
        scope='Synthetic result protocol, displayed pixels and standalone mapped resources; no real recognition, CDC timing closure, integration or board claim')
    (DOC/'final-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(reports,indent=2));print('Evidence frozen; independent review text differences:',changed)


if __name__=='__main__':main()
