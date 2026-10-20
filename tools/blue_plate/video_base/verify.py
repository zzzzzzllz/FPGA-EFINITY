"""Check source protection, mapped resources and (when present) place/timing reports."""
import argparse
import json
import re
from generate import SOURCE, WORK, sha


def verify(variant):
    work = WORK / variant
    inputs = json.loads((work / 'inputs.json').read_text(encoding='utf-8'))
    for rel, digest in inputs['source_sha256'].items():
        if sha(SOURCE / rel) != digest:
            raise ValueError(f'Original source changed since snapshot: {rel}')
    for rel, digest in inputs['candidate_sha256'].items():
        if sha(work / rel) != digest:
            raise ValueError(f'Candidate input changed since snapshot: {rel}')
    out = work / 'outflow'
    name = inputs['name']
    result = {'original_source_hashes': len(inputs['source_sha256']), 'original_source': 'PASS', 'candidate_inputs': 'PASS'}
    mapped = out / (name + '.map.rpt')
    if mapped.exists():
        text = mapped.read_text(errors='replace')
        summary = text.split('Resource Summary (begin)', 1)[1].split('Resource Summary (end)', 1)[0]
        primitives = {m.group(1): int(m.group(2)) for m in re.finditer(r'^(EFX_\w+)\s*:\s*(\d+)', summary, re.M)}
        ram = sum(v for k, v in primitives.items() if k in ('EFX_RAM10', 'EFX_DPRAM10'))
        dsp = sum(v for k, v in primitives.items() if k.startswith('EFX_DSP'))
        if ram > inputs['limits']['Memory Blocks'] or dsp > inputs['limits']['DSP Blocks']:
            raise ValueError('Mapped RAM/DSP budget exceeded')
        # Exact XLR accounting includes placement/packing; do not equate LUTs with XLRs.
        if max(primitives.get('EFX_LUT4', 0), primitives.get('EFX_FF', 0)) > inputs['limits']['XLRs']:
            raise ValueError('Mapped logic lower bound exceeds XLR budget')
        result['mapped_primitives'] = primitives
        result['mapped_memory_dsp_blocks'] = [ram, dsp]
        result['XLR_budget_verdict'] = 'pending placement'
        netlist = (out / (name + '.map.v')).read_text(errors='replace')
        for hierarchy in ('full_view/', 'checker0/capture_fifo/', 'checker0/result_fifo/', 'u_ddr3_top/', 'cvo_axi_inst/'):
            if hierarchy not in netlist:
                raise ValueError(f'Missing live video hierarchy: {hierarchy}')
        result['live_hierarchy_present'] = True
        if variant == 'live':
            for removed in ('checker0/shapes/engine/', 'checker0/canny/engine/', 'checker0/control/clip_id',
                            'checker0/control/recorded_slots', 'algorithm_pipeline/median/',
                            'algorithm_pipeline/gaussian/', 'algorithm_pipeline/gradient_stage/',
                            'algorithm_pipeline/nms_stage/', 'user_controls/', 'threshold_overlay/menu_rom'):
                if removed in netlist:
                    raise ValueError(f'Unexpected demo/history logic remains: {removed}')
            result['demo_history_hierarchies_removed'] = True
    place = out / (name + '.place.rpt')
    place_current = place.exists() and mapped.exists() and place.stat().st_mtime >= mapped.stat().st_mtime
    if place_current:
        text = place.read_text(errors='replace')
        resources = {}
        for label, limit in inputs['limits'].items():
            match = re.search(r'^' + label + r':\s*(\d+)\s*/\s*(\d+)', text, re.M)
            if not match:
                raise ValueError(f'Missing resource: {label}')
            used, total = map(int, match.groups())
            resources[label] = {'used': used, 'physical_total': total, 'limit': limit, 'budget_left': limit - used}
            if used > limit:
                raise ValueError(f'Resource budget exceeded: {label} {used}>{limit}')
        result['placed_resources'] = resources
        result['XLR_budget_verdict'] = 'PASS'
    timing = out / (name + '.timing.rpt')
    if place_current and timing.exists() and timing.stat().st_mtime >= place.stat().st_mtime:
        text = timing.read_text(errors='replace')
        sections = (text.split('Setup (Max) Clock Relationship', 1)[1].split('Hold (Min)', 1)[0],
                    text.split('Hold (Min) Clock Relationship', 1)[1].split('NOTE:', 1)[0])
        slacks = []
        for section in sections:
            values = [float(m.group(1)) for m in re.finditer(r'^\S+\s+\S+\s+[\d.]+\s+(-?[\d.]+)\s+\(', section, re.M)]
            if not values or min(values) < 0:
                raise ValueError('Timing did not pass')
            slacks.append(min(values))
        result['timing_min_setup_hold_slack_ns'] = slacks
        result['clock_self_slack_ns'] = {}
        for clock in ('core_clk', 'i_mipi_rx_pclk', 'hdmi_tx_slow_clk'):
            result['clock_self_slack_ns'][clock] = []
            for section in sections:
                match = re.search(r'^' + clock + r'\s+' + clock + r'\s+[\d.]+\s+(-?[\d.]+)\s+\(', section, re.M)
                if not match:
                    raise ValueError(f'Missing clock timing relationship: {clock}')
                result['clock_self_slack_ns'][clock].append(float(match.group(1)))
    (work / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variant', choices=('gates', 'live'))
    verify(parser.parse_args().variant)
