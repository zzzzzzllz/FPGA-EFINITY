"""Check the CLI page protocol without a board or Efinity installation."""
import json
import re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'tools'))
from paged_status import read_snapshot

layout=json.loads((Path(__file__).resolve().parents[1].parent/'status_snapshot.json').read_text())
expected={p['name']: ((0x123456789abcdef << (i%4)) + i) & ((1<<p['width'])-1)
          for i,p in enumerate(layout['probes'])}
packed=sum(expected[p['name']]<<p['offset'] for p in layout['probes'])

class Manager:
    page=0
    capture=0
    old=True
    writes=0
    sensor_ack=1

    def vio_write(self, debug, core, values):
        assert core=='snapshot', 'Read operation touched camera controls'
        self.page,self.capture,sensor_command=values
        assert sensor_command == self.sensor_ack << 25, 'Snapshot triggered a sensor command'
        self.old=True
        self.writes+=1

    def vio_read(self, debug, core):
        assert core=='snapshot'
        if self.old:
            self.old=False
            return [0,self.page,self.capture^1,4|self.sensor_ack]
        return [(packed>>(64*self.page))&((1<<64)-1),self.page,self.capture,4|self.sensor_ack]

manager=Manager()
assert read_snapshot(manager,None,layout,lambda v,length:v)==expected
assert manager.writes==layout['pages']
print(f'PASS {len(expected)} fields, {layout["pages"]} pages, stale acknowledgements, controls untouched')

# The paged reader and direct VIO must identify the same loaded program.
project=Path(__file__).resolve().parents[2]
top=(project/'rtl/ti60f225_oob_top.v').read_text(encoding='utf-8')
control=(project/'control.py').read_text(encoding='utf-8')
snapshot_id=re.search(r"assign debug_live\[0 \+: 32\]=32'h([0-9a-fA-F]+)",top)
direct_id=re.search(r"\.status_build_id\(32'h([0-9a-fA-F]+)\)",top)
expected_id=re.search(r'expected_id = 0x([0-9a-fA-F]+)',control)
assert snapshot_id and direct_id and expected_id, 'Missing program identity'
assert len({int(m.group(1),16) for m in (snapshot_id,direct_id,expected_id)})==1, 'Snapshot, direct VIO and CLI build IDs differ'
print('PASS snapshot/direct VIO/CLI build IDs match')

