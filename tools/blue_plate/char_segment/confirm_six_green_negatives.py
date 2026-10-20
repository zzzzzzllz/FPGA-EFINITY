"""Rebuild six authorized development patches, freeze inputs, then six integer calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import torch

from experiment import resize_q8, grammar
from integer_lprnet_fork import ForkLPR
from ctc_interval import collapse, emissions, ctc_bounds

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'tools/blue_plate'))
from compare_hyperlpr import inspected_functions
from probe_hyperlpr_rejection import canvas720
from geometry_sampler import sample_integer
from diagnose_color_evidence import color_evidence

DATA = ROOT/'tmp/blue-plate-char-segment'
DET = ROOT/'tmp/blue-plate-normal-g1/mature-detector'
MODEL = DATA/'quantization-tap2-fork'
OUT = DATA/'six-green-negatives'
SAMPLES = [217, 271, 341, 376, 381, 466]
UPSTREAM = ROOT/'tmp/blue-plate-review/mature-research/hyperlpr'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def array_info(a):
    return dict(shape=list(a.shape), dtype=a.dtype.str,
                sha256_c_order_bytes=hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest())


def source_files():
    paths = [Path(__file__), ROOT/'tools/blue_plate/geometry_sampler.py',
        ROOT/'tools/blue_plate/diagnose_color_evidence.py', ROOT/'tools/blue_plate/probe_hyperlpr_rejection.py',
        ROOT/'tools/blue_plate/compare_hyperlpr.py', Path(__file__).with_name('experiment.py'),
        Path(__file__).with_name('integer_lprnet.py'),Path(__file__).with_name('integer_lprnet_fork.py'),
        Path(__file__).with_name('ctc_interval.py'), MODEL/'integer-config.json',MODEL/'integer-parameters.npz',
        DATA/'ctc-q30/lut.json', DATA/'pretrained-new-rois/config.json',
        DATA/'experiment/dev-manifest.json', DATA/'pretrained-new-rois/gates.json',
        DATA/'color-cnn-ablation/synthetic-color-exclusive-cases.json',
        DET/'comparison-records.json',DET/'color-evidence-development/records.json',DET/'rejection-probe/records.json',
        UPSTREAM/'Prj-Python/hyperlpr3/common/tools_process.py',
        UPSTREAM/'Prj-Python/hyperlpr3/inference/classification.py']
    return {relative(p):sha(p) for p in paths}


def prepare():
    if OUT.exists():
        raise FileExistsError(OUT)
    OUT.mkdir(parents=True)
    sources = source_files()
    original = {r['sample_index']:r for r in read(DET/'comparison-records.json')
                if r['split']=='development' and r['sample_index'] in SAMPLES}
    dev = [r for r in read(DATA/'experiment/dev-manifest.json')['records'] if r['sample_index'] in SAMPLES]
    gates = {r['roi_index']:r for r in read(DATA/'pretrained-new-rois/gates.json') if r['sample_index'] in SAMPLES}
    historic = {r['sample_index']:r for r in read(DATA/'color-cnn-ablation/synthetic-color-exclusive-cases.json')}
    evidence = {r['sample_index']:r['outputs'][0]['color_evidence'] for r in read(DET/'color-evidence-development/records.json')
                if r['kind']=='synthetic_green_patch' and r['sample_index'] in SAMPLES}
    assert set(original)==set(historic)==set(evidence)==set(SAMPLES)
    warp_path=UPSTREAM/'Prj-Python/hyperlpr3/common/tools_process.py'
    pinned=read(UPSTREAM/'manifest.json')
    expected=next(p['sha256'] for p in pinned['files'] if p['path']==warp_path.relative_to(UPSTREAM).as_posix())
    assert sha(warp_path)==expected
    warp=inspected_functions(warp_path,['get_rotate_crop_image'])['get_rotate_crop_image']
    arrays, rows, mismatches = {}, [], []
    for sample in SAMPLES:
        item=original[sample]
        anchor=max(item['detector320'],key=lambda r:r['detector_confidence'])
        candidates=[r for r in dev if r['sample_index']==sample and r['points']==anchor['points']]
        assert len(candidates)==1
        prior=candidates[0]
        assert prior['original_split']=='development' and prior['teacher_cached']['box']==anchor['box']
        assert prior['path']==item['path']==historic[sample]['source']
        image_path=ROOT/item['path']
        assert sha(image_path)==prior['source_sha256']
        source=cv2.imdecode(np.fromfile(image_path,np.uint8),cv2.IMREAD_COLOR)
        if source is None:
            raise ValueError(f'Cannot decode authorized image {sample}')
        frame=canvas720(source)
        native=warp(frame,np.array(anchor['points']))
        hsv=cv2.cvtColor(native,cv2.COLOR_BGR2HSV)
        mask=hsv[...,1]>60
        hsv[...,0][mask]=60
        green=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
        ev=color_evidence(green)
        old=evidence[sample]
        match=ev==old
        if not match:
            mismatches.append(dict(sample_index=sample,expected=old,reconstructed=ev))
        # Existing downstream-patch route: outer corners -> Q32/Q5 224x64 -> Q8 24x94.
        h,w=green.shape[:2]
        corners=np.array([[0,0],[w-1,0],[w-1,h-1],[0,h-1]])
        fixed,matrix=sample_integer(green,corners,32,integer_solver=True)
        q8=resize_q8(fixed,24,94)
        cnn_native=cv2.resize(green,(96,96))
        cnn_fixed=cv2.resize(fixed,(96,96))
        key=f'sample{sample}'
        values=dict(native=native,green=green,fixed_bgr=fixed,q8_bgr=q8,native_cnn96=cnn_native,fixed_cnn96=cnn_fixed)
        for suffix,value in values.items():
            arrays[f'{key}.{suffix}']=value
        if not cv2.imwrite(str(OUT/f'{sample}-green.png'),green):
            raise IOError('Cannot write reconstructed patch')
        g=gates[prior['roi_index']]
        assert g['corner_margin']>=1 and g['box_margin']>=1
        cnn=historic[sample]
        assert cnn['color_class']==max(range(3),key=lambda j:cnn['color_scores'][j])!=0
        assert cnn['blue_count']==old['counts']['blue_hs'] and cnn['yellow_count']==old['counts']['yellow_hs']
        rows.append(dict(sample_index=sample,original_development_roi_index=prior['roi_index'],source=item['path'],
            source_sha256=prior['source_sha256'],source_shape=list(source.shape),original_transcript=item['label'],
            expected_output='reject_nonblue_synthetic_patch',expected_color='synthetic_green_recolor',
            anchor_points=anchor['points'],anchor_box=anchor['box'],detector_confidence=anchor['detector_confidence'],
            source_frame_sha256=array_info(frame)['sha256_c_order_bytes'],recolor_pixels=int(mask.sum()),
            native_hs_evidence=ev,historical_hs_evidence=old,all_hs_evidence_exact_match=match,
            historical_native_color_class=cnn['color_class'],historical_native_color_scores=cnn['color_scores'],
            classifier_rerun=False,old_edited_pixel_hash_available=False,
            original_frame_boundary=dict(corner_margin=g['corner_margin'],box_margin=g['box_margin'],pass_gate=True),
            edited_fullframe_boundary=None,patch_corners=corners.tolist(),patch_inverse_q32=matrix.tolist(),
            arrays={suffix:dict(key=f'{key}.{suffix}',**array_info(value)) for suffix,value in values.items()},
            fixed_native_cnn96_equal=bool(np.array_equal(cnn_native,cnn_fixed)),
            fixed_native_cnn96_different_values=int(np.count_nonzero(cnn_native!=cnn_fixed)),
            fixed_native_cnn96_max_abs_difference=int(np.abs(cnn_native.astype(np.int16)-cnn_fixed.astype(np.int16)).max())))
    write(OUT/'reconstruction-records.json',rows)
    write(OUT/'reconstruction-mismatches.json',mismatches)
    np.savez_compressed(OUT/'inputs.npz',**arrays)
    if mismatches:
        raise ValueError('Reconstruction differs from historical evidence; do not treat as the same negative or run inference')
    assert sources==source_files()
    artifacts=[OUT/'reconstruction-records.json',OUT/'reconstruction-mismatches.json',OUT/'inputs.npz']
    artifacts += [OUT/f'{s}-green.png' for s in SAMPLES]
    write(OUT/'input-freeze.json',dict(samples=SAMPLES,source_hashes=sources,
        artifacts={relative(p):sha(p) for p in artifacts},source_image_reads=6,detector_inferences=0,color_inferences=0,ocr_inferences=0,
        provenance='Newly frozen reconstruction, not a byte-identical comparison to old edited pixels: those hashes were never stored.',
        reconstruction='Original cached detector320 highest-score integer corners; original canvas720 and cubic native warp; BGR->HSV, S>60 set H=60, HSV->BGR.',
        ocr_entry='Existing downstream patch route: four outer pixel corners -> integer Q32/Q5 224x64 BGR -> frozen resize_q8 24x94 -> ForkLPR.',
        color_entry='Historical native patch -> cv2 linear96x96 -> /255 CHW; fixed224x64 is not a substitute.',
        boundary='Source-frame boundary is provenance only; no edited full-frame detection or boundary measurement.',
        expected_output='reject_nonblue_synthetic_patch',versions=dict(opencv=cv2.__version__,numpy=np.__version__,torch=torch.__version__)))
    print('Prepared and frozen exactly six reconstructed patches; all stored color evidence fields match.')


def check_freeze():
    frozen=read(OUT/'input-freeze.json')
    assert frozen['samples']==SAMPLES and frozen['source_hashes']==source_files()
    assert all(sha(ROOT/p)==h for p,h in frozen['artifacts'].items())
    assert read(OUT/'reconstruction-mismatches.json')==[]
    return frozen


def infer():
    if (OUT/'inference-start.json').exists():
        raise FileExistsError('Six-call run already started; do not silently repeat inference')
    frozen=check_freeze()
    records=read(OUT/'reconstruction-records.json')
    cfg=read(MODEL/'integer-config.json')
    with np.load(MODEL/'integer-parameters.npz',allow_pickle=False) as z:
        parameters={k:z[k] for k in z.files}
    classes=read(DATA/'pretrained-new-rois/config.json')['classes']
    lut=read(DATA/'ctc-q30/lut.json')
    table=[(x,x if i==0 else x+1) for i,x in enumerate(lut['lower'])]
    table += [tuple(lut['tail_bounds'])]*(1021-len(table))
    model=ForkLPR(cfg,parameters)
    write(OUT/'inference-start.json',dict(samples=SAMPLES,input_freeze_sha256=sha(OUT/'input-freeze.json'),
        maximum_forward_calls=6,optimizer_steps=0,threshold_search=False,confidence_bits=30))
    results,logits=[],[]
    with np.load(OUT/'inputs.npz',allow_pickle=False) as inputs:
        for row in records:
            sample=row['sample_index']
            input_meta=row['arrays']['q8_bgr']
            image=inputs[input_meta['key']]
            assert array_info(image)=={k:v for k,v in input_meta.items() if k!='key'}
            q,trace,stats,_=model(image)
            a=q[0].numpy().copy()
            path=a.argmax(axis=0).tolist()
            target=collapse(path,67)
            code=''.join(classes[i] for i in target)
            legal=bool(grammar(code))
            diff=(a.astype(np.int32).max(axis=0,keepdims=True)-a.astype(np.int32)).T
            assert diff.min()>=0 and diff.max()<=1020
            probability=emissions(diff,table,30)
            bounds=ctc_bounds(probability,target,30)
            status='accept' if bounds[0]>=1023453813 else 'reject' if bounds[1]<1023453813 else 'undecided'
            ocr=status if legal else 'grammar_reject'
            hs=row['native_hs_evidence']['hs_blue_over_yellow']
            cnn=row['historical_native_color_class']==0
            before=legal and hs and cnn and status=='accept'
            after=legal and hs and status=='accept'
            result=dict(sample_index=sample,expected_output=row['expected_output'],code=code,greedy_path=path,
                decoded_ids=target,legal=legal,dp_state_count=2*len(target)+1,hardware_15_state_eligible=legal,
                bounds_q30=list(bounds),raw_interval_status=status,ocr_status=ocr,
                native_hs_pass=hs,historical_native_cnn_blue=cnn,
                patch_with_cnn_accept=before,patch_without_cnn_accept=after,
                newly_accepted_nonblue_patch=after and not before,
                source_boundary_conditioned_with_cnn_accept=before and row['original_frame_boundary']['pass_gate'],
                source_boundary_conditioned_without_cnn_accept=after and row['original_frame_boundary']['pass_gate'],
                edited_fullframe_acceptance=None,fullframe_boundary_measured=False,
                input_sha256=input_meta['sha256_c_order_bytes'],logits=array_info(a),
                context_gain_bits={k:v['gain_bits'] for k,v in stats.items() if 'gain_bits' in v})
            results.append(result)
            logits.append(a)
            write(OUT/f'{sample}-result.json',result)
            print(json.dumps(result,ensure_ascii=True),flush=True)
    assert len(results)==6
    np.savez_compressed(OUT/'integer-logits.npz',logits=np.stack(logits))
    write(OUT/'results.json',results)
    assert frozen==check_freeze()
    write(OUT/'run-summary.json',dict(samples=SAMPLES,forward_calls=6,source_image_reads_during_inference=0,
        detector_inferences=0,color_inferences=0,optimizer_steps=0,threshold_search=False,
        legal=sum(r['legal'] for r in results),with_cnn_patch_accepts=sum(r['patch_with_cnn_accept'] for r in results),
        without_cnn_patch_accepts=sum(r['patch_without_cnn_accept'] for r in results),
        new_nonblue_patch_accepts=sum(r['newly_accepted_nonblue_patch'] for r in results),
        undecided=sum(r['ocr_status']=='undecided' for r in results),edited_fullframe_false_accepts=None,
        input_freeze_unchanged=True,claim='Six reconstructed downstream patches, not a new full-frame evaluation.'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['prepare','infer'])
    args=parser.parse_args()
    cv2.setNumThreads(2)
    torch.set_num_threads(4)
    prepare() if args.stage=='prepare' else infer()
