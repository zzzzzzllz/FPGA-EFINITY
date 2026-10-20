"""Generate isolated video-base candidates without modifying the edge project."""
import argparse
import difflib
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'coding/edge-quality-30fps'
WORK = ROOT / 'tmp/blue-plate-video-base'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Expected one source anchor: {old[:90]}')
    return text.replace(old, new, 1)


def generate(variant):
    work = WORK / variant
    # Preserve prior reports. A rerun requires a fresh directory selected by the caller.
    work.mkdir(parents=True, exist_ok=False)
    original = {str(p.relative_to(SOURCE)).replace('\\', '/'): sha(p)
                for p in SOURCE.rglob('*') if p.is_file()}
    for p in SOURCE.iterdir():
        if p.name in ('release', 'tests', 'config') or p.suffix in ('.cmd', '.py'):
            continue
        if p.is_dir():
            shutil.copytree(p, work / p.name)
        else:
            shutil.copy2(p, work / p.name)
    name = 'blue_plate_video_' + variant
    top_path = work / 'rtl/ti60f225_oob_top.v'
    top = top_path.read_text(encoding='utf-8')
    top = replace_once(top, '.ENABLE_CANNY(1),.ENABLE_SHAPE(1)', '.ENABLE_CANNY(0),.ENABLE_SHAPE(0)')
    if variant == 'live':
        start = top.index('edge_ui user_controls(')
        end = top.index('assign gray_sel=', start)
        top = top[:start] + '''// Dedicated live color configuration; no historical commands enter the backend.
assign ui_view=0;assign ui_recognition=0;assign ui_median=0;assign ui_algorithm=0;assign ui_ratio=0;
assign ui_short_events=0;assign ui_long_events=0;
assign ui_error=0;assign ui_busy=0;assign demo_step=1;
assign threshold_preset=0;assign threshold_preset_value=0;
assign ui_apply_ack=0;assign jtag_frame_ack=0;
assign frame_command=0;assign frame_command_toggle=0;
''' + top[end:]
        top = replace_once(top, '.config_value({ratio_active,algorithm_active,denoise_active,median_active,threshold_active}),.config_epoch(config_epoch+threshold_epoch+median_epoch)', '.config_value(16\'d0),.config_epoch(config_epoch)')
        top = replace_once(top, 'edge_algorithm_pair algorithm_pipeline(', 'video_rgb_passthrough algorithm_pipeline(')
        shutil.copy2(Path(__file__).with_name('video_rgb_passthrough.v'), work / 'rtl/video_rgb_passthrough.v')
        # Keep the existing metadata receiver and frame shown acknowledgement.
        osd_path = work / 'rtl/threshold_osd.v'
        osd = osd_path.read_text(encoding='utf-8')
        osd = osd[:osd.index(' reg [7:0] character;')] + ' assign out_rgb=rgb;\nendmodule\n'
        osd_path.write_text(osd, encoding='utf-8')
    top_path.write_text(top, encoding='utf-8')
    xml = (work / 'ti60f225_oob.xml').read_text(encoding='utf-8')
    xml = replace_once(xml, 'name="ti60f225_oob" description="Edge stage 4: full-field gray and Sobel comparison"', f'name="{name}" description="Isolated blue plate live video resource candidate: {variant}"')
    xml = xml.replace('ti60f225_oob.peri.xml', name + '.peri.xml')
    if variant == 'live':
        xml = replace_once(xml, 'name="rtl/edge_algorithm_pair.v"', 'name="rtl/video_rgb_passthrough.v"')
    (work / (name + '.xml')).write_text(xml, encoding='utf-8')
    (work / 'ti60f225_oob.xml').unlink()
    peri = (work / 'ti60f225_oob.peri.xml').read_text(encoding='utf-8')
    peri = replace_once(peri, 'name="ti60f225_oob" device_def=', f'name="{name}" device_def=')
    (work / (name + '.peri.xml')).write_text(peri, encoding='utf-8')
    (work / 'ti60f225_oob.peri.xml').unlink()
    changes = []
    for rel in ('rtl/ti60f225_oob_top.v', 'rtl/threshold_osd.v'):
        changes.extend(difflib.unified_diff((SOURCE / rel).read_text(encoding='utf-8').splitlines(True),
                                          (work / rel).read_text(encoding='utf-8').splitlines(True),
                                          fromfile='source/' + rel, tofile='candidate/' + rel))
    (work / 'candidate.diff').write_text(''.join(changes), encoding='utf-8')
    manifest = {'variant': variant, 'name': name, 'source': str(SOURCE),
                'source_sha256': original,
                'candidate_sha256': {p.relative_to(work).as_posix(): sha(p) for p in work.rglob('*') if p.is_file()},
                'limits': {'XLRs': 49248, 'Memory Blocks': 204, 'DSP Blocks': 128}}
    (work / 'inputs.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(work)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variant', choices=('gates', 'live'))
    generate(parser.parse_args().variant)
