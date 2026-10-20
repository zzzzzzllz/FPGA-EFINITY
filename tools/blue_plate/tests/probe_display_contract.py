"""Isolated event-level proposal, not RTL. Source TTL remains 500 ms.

Uses integer microseconds to expose source-age, arrival and frame-commit delays.
Existing RTL tests cover modular counters and CDC; this probe does not model them.
"""
import hashlib
import json
from pathlib import Path

TTL = 500_000


class State:
    def __init__(self, confirmations):
        self.required = confirmations
        self.last_id = -1
        self.last_stamp = -1
        self.support = None
        self.count = 0
        self.pending = None
        self.active = None
        self.clear = False
        self.config = 1

    def receive(self, now, frame_id, stamp, code, config=1):
        if config != self.config or frame_id <= self.last_id or stamp < self.last_stamp or stamp > now:
            return
        self.last_id, self.last_stamp = frame_id, stamp
        if code is None or now-stamp >= TTL:
            self.count = 0
            self.support = self.pending = None
            self.clear = True
            return
        continuation = self.support is not None and self.support[1] == code and now-self.support[0] < TTL
        self.count = min(self.required, self.count+1) if continuation else 1
        self.support = (stamp, code)
        self.pending = self.support if self.count == self.required else None

    def frame_start(self, now):
        self.active = self.pending if self.pending is not None and 0 <= now-self.pending[0] < TTL and not self.clear else None
        if self.pending is not None and now-self.pending[0] >= TTL:
            self.pending = None
        self.clear = False

    def change_config(self, config):
        self.config = config
        self.last_id = self.last_stamp = -1
        self.count = 0
        self.support = self.pending = None
        self.clear = True


def cadence(required, latency, interval):
    state = State(required)
    arrivals = {latency+i*interval: (i+1, i*interval) for i in range(6)}
    end = latency+5*interval+TTL+33333
    boundaries = set(range(0, end+1, 33333))
    max_count, visible, transitions, total = 0, 0, [], 0
    previous = None
    for now in sorted(boundaries | arrivals.keys()):
        if now in arrivals:
            state.receive(now, *arrivals[now], 'same_valid_number')
            max_count = max(max_count, state.count)
        if now in boundaries:
            state.frame_start(now)
            total += 1
            visible += int(state.active is not None)
            shown = state.active is not None
            if shown != previous:
                transitions.append(dict(time_us=now, visible=shown))
                previous = shown
    assert state.active is None
    return dict(required=required, latency_us=latency, source_interval_us=interval,
                max_count=max_count, display_frames=total, visible_frames=visible, transitions=transitions)


def main():
    results = []
    for latency in [249000, 250000, 416138, 602500]:
        for required in [1, 3]:
            row = cadence(required, latency, latency)
            expected = latency < TTL and (required == 1 or latency*2 < TTL)
            assert (row['visible_frames'] > 0) == expected
            results.append(row)
    s = State(1)
    s.receive(420000, 2, 100000, 'new')
    s.frame_start(430000)
    assert s.active == (100000, 'new')
    s.receive(440000, 1, 0, 'old')
    s.receive(450000, 2, 100000, 'duplicate')
    s.receive(460000, 1, 0, None)
    s.frame_start(470000)
    assert s.active == (100000, 'new')
    s.receive(480000, 3, 470000, None)
    assert s.active == (100000, 'new')  # No mid-frame mutation.
    s.frame_start(490000)
    assert s.active is None
    s.receive(510000, 4, 500000, 'next')
    s.change_config(2)
    s.receive(520000, 5, 510000, 'old_config', config=1)
    s.frame_start(530000)
    assert s.active is None
    s.receive(540000, 1, 530000, 'configured', config=2)
    s.frame_start(550000)
    assert s.active is not None
    s.frame_start(1030000)
    assert s.active is None
    s.receive(1040000, 2, 1050000, 'future', config=2)
    s.frame_start(1050000)
    assert s.active is None
    # A fresh-on-arrival packet can expire while waiting for frame boundary.
    s = State(1)
    s.receive(499000, 1, 0, 'late')
    s.frame_start(500000)
    assert s.active is None
    # Repeated same wrong OCR on distinct synthetic sources passes three votes
    # if cadence allows. This is a logic counterexample, not real video evidence.
    s = State(3)
    for i in range(3):
        s.receive(i*100000+100000, i+1, i*100000, 'same_wrong_number')
    s.frame_start(310000)
    assert s.active == (200000, 'same_wrong_number')
    out = Path('tmp/blue-plate-normal-g1/mature-detector/display-contract-proposal')
    out.mkdir(exist_ok=True)
    report = dict(ttl_ms=500, scope='Event model only; no production RTL changes, no CDC/DDR/performance validation.',
                  cadence=results, old_duplicate_and_old_reject_ignored=True, reject_clears_at_boundary=True,
                  configuration_invalidates=True, future_and_expired_rejected=True,
                  commit_checks_source_age=True, stable_wrong_can_pass_three_votes=True,
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print('PASS 8 cadence cases plus order, duplicate, rejection, config, deadline and repeated-error checks; TTL=500 ms')


if __name__ == '__main__':
    main()
