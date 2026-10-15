"""Check the CLI page protocol without a board or Efinity installation."""
import json
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

