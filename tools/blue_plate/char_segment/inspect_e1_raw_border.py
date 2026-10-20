"""Post-run completeness diagnostic only; never modifies E1 selection."""
import cv2
import numpy as np

from run_edge_local_e1 import OUT, read, write_new
from edge_local_refine import gray_from_bgr
from bounded_edge_locator import STRUCTURE, array_hash


def main():
    records = []
    for path in sorted((OUT / 'frames').glob('*.json')):
        row = read(path)
        index = row['selection']['selected_index']
        if index is None:
            continue
        line = row['selection']['hypotheses'][index]
        uid = line['source_coarse_uids'][0]
        coarse = next(c for c in row['refinements'] if c['uid'] == uid)
        number = next(i for i, c in enumerate(coarse['refinements']) if c['points_q16'] == line['points_q16'])
        with np.load(OUT / 'crops' / f"{row['sample_index']:03d}.npz", allow_pickle=False) as cache:
            patch = cache[f'refined_{uid}_{number}']
            assert array_hash(patch) == line['original_bgr_sha256']
        gray = gray_from_bgr(patch)
        polarities = []
        for name, image in [('light', gray), ('dark', 255-gray)]:
            raw = STRUCTURE['otsu32'](image)
            if raw is None:
                polarities.append(dict(polarity=name, status='single_bin'))
                continue
            _, _, stats, _ = cv2.connectedComponentsWithStats(raw.astype(np.uint8), connectivity=8)
            touching = []
            for x, y, w, h, area in stats[1:]:
                if h >= 23 and 1 <= w <= 36 and (x == 0 or y == 0 or x+w == 224 or y+h == 64):
                    touching.append(dict(box=[int(x), int(y), int(x+w), int(y+h)], area=int(area)))
            polarities.append(dict(polarity=name, raw_mask_sha256=array_hash(raw),
                                   character_sized_border_components=touching,
                                   before_cleanup_border_foreground=int(raw[0].sum()+raw[-1].sum()+raw[1:-1, 0].sum()+raw[1:-1, -1].sum())))
        records.append(dict(sample_index=row['sample_index'], polarities=polarities))
    flagged = [r['sample_index'] for r in records if any(p.get('character_sized_border_components') for p in r['polarities'])]
    report = dict(status='POSTHOC_DIAGNOSTIC_NOT_AN_E1_GATE', source_image_reads=0, local_refinement_calls=0,
        model_forwards=0, cached_selected_rois=70, threshold='same frozen otsu32; both polarities',
        component_rule='h>=23, 1<=w<=36, touches raw 224x64 boundary; before clearing rows/columns',
        warning='This flag is neither a trained character classifier nor a verified completeness guarantee.',
        flagged_ids=flagged, records=records)
    write_new(OUT / 'raw-border-diagnostic.json', report)
    write_new(OUT / 'visual-review.json', dict(status='E1_NOT_READY_FOR_OCR',
        reviewed_selected_cache_count=70, confirmed_visual_character_clipping=[164],
        other_selected_clipping='No additional obvious cut identified in contact sheets; not pixel-annotated proof.',
        sample164=dict(observation='Top portions of characters absent from final ROI but visible in original coarse cache.',
                       underlying_mask='selected observed groups only 16..19 pixels tall; original-size global threshold omits upper strokes',
                       failed_guard='search-boundary guard passes; final raw crop boundary was not checked before structure clears margins',
                       gt_foreground_diagnostic='unknown, not negative', selection_changed=False),
        images=['inspection.png', 'selected-crops-1.png', 'selected-crops-2.png', 'sample-164-inspection.png'],
        source_image_reads=0, new_local_refinements=0, model_forwards=0))
    print('Diagnostic flagged cached selected IDs:', flagged)


if __name__ == '__main__':
    main()
