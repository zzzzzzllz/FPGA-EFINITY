"""Plot frozen selected BGR caches; never reopen source images or rerun E1."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from run_edge_local_e1 import OUT, read


def main():
    records = [read(p) for p in sorted((OUT / 'frames').glob('*.json'))]
    selected = [r for r in records if r['selection']['selected_index'] is not None]
    for page in range(2):
        fig, axes = plt.subplots(9, 4, figsize=(12, 10))
        for ax in axes.ravel():
            ax.axis('off')
        for ax, row in zip(axes.ravel(), selected[page*36:(page+1)*36]):
            line = row['selection']['hypotheses'][row['selection']['selected_index']]
            uid = line['source_coarse_uids'][0]
            coarse = next(c for c in row['refinements'] if c['uid'] == uid)
            idx = next(i for i, c in enumerate(coarse['refinements']) if c['points_q16'] == line['points_q16'])
            with np.load(OUT / 'crops' / f"{row['sample_index']:03d}.npz", allow_pickle=False) as cache:
                ax.imshow(cache[f'refined_{uid}_{idx}'][:, :, ::-1])
            ax.set_title(f"{row['sample_index']} | IoU {line['evaluation']['iou']:.3f}", fontsize=9)
        fig.suptitle(f'E1 frozen selected crops {page+1}/2: inspection only, no OCR', fontsize=12)
        fig.tight_layout()
        fig.savefig(OUT / f'selected-crops-{page+1}.png', dpi=150)
        plt.close(fig)
    row = next(r for r in selected if r['sample_index'] == 164)
    line = row['selection']['hypotheses'][row['selection']['selected_index']]
    uid = line['source_coarse_uids'][0]
    coarse = next(c for c in row['refinements'] if c['uid'] == uid)
    idx = next(i for i, c in enumerate(coarse['refinements']) if c['points_q16'] == line['points_q16'])
    with np.load(OUT / 'crops/164.npz', allow_pickle=False) as cache:
        fig, axes = plt.subplots(1, 2, figsize=(10, 3))
        for ax, key, label in zip(axes, [f'coarse_{uid}', f'refined_{uid}_{idx}'], ['Original coarse crop', 'Frozen final crop; GT foreground diagnostic unknown']):
            ax.imshow(cache[key][:, :, ::-1]); ax.set_title(label, fontsize=9); ax.axis('off')
        fig.tight_layout(); fig.savefig(OUT / 'sample-164-inspection.png', dpi=150); plt.close(fig)
    print('Saved 70 selected cached crops; no source-image reads or algorithm calls')


if __name__ == '__main__':
    main()
