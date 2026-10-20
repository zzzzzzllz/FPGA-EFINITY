"""One frozen Q30 CTC interval validation on existing integer logits only."""
from collections import Counter, defaultdict
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import product
from pathlib import Path
import math
import time

import numpy as np

from experiment import ROOT, read_json, write_json, sha, grammar
from fixed_lprnet import STRICT_THRESHOLD
from ctc_interval import rational_bounds, exp_certificate, collapse, emissions, ctc_bounds, decision, rank_candidates

OUT = ROOT/'tmp/blue-plate-char-segment/ctc-q30'
MODEL = ROOT/'tmp/blue-plate-char-segment/quantization-tap2-fork'
VAL = ROOT/'tmp/blue-plate-char-segment/quantization-fork-validation'
DEV = ROOT/'tmp/blue-plate-char-segment/pretrained-new-rois'
Q = 1 << 30
H = 1 << 128


def synthetic_checks(threshold):
    checks = 0
    for length in (0, 1, 2, 3, 4):
        columns = [[Fraction(1,2), Fraction(1,3), Fraction(1,6)] if t%2==0 else
                   [Fraction(1,4), Fraction(1,4), Fraction(1,2)] for t in range(length)]
        truth = defaultdict(Fraction)
        for path in product(range(3), repeat=length):
            p = math.prod(columns[t][c] for t,c in enumerate(path))
            truth[tuple(collapse(path, 2))] += p
        for target in set(truth) | {(0,0),(1,1),(0,)*5,()}:
            bounds = ctc_bounds([[rational_bounds(p,30) for p in row] for row in columns], list(target),30,blank=2)
            exact = truth[target]
            assert Fraction(bounds[0],Q) <= exact <= Fraction(bounds[1],Q)
            checks += 1
    assert collapse([0,0,2,0],2)==[0,0] and collapse([2,2],2)==[]
    target=[0,0,1,1,0,1,0]
    path=[]
    for c in target:
        if path and path[-1]==c:path.append(2)
        path.append(c)
    path += [2]*(18-len(path))
    deterministic=[[(Q,Q) if c==chosen else (0,0) for c in range(3)] for chosen in path]
    assert ctc_bounds(deterministic,target,30,2)==(Q,Q)
    assert ctc_bounds(deterministic,[0]*19,30,2)==(0,0)
    assert ctc_bounds([[(0,0),(0,0),(Q,Q)]]*18,[],30,2)==(Q,Q)
    lo,hi=rational_bounds(threshold,30)
    assert decision((lo,lo),threshold)=='reject'
    assert decision((hi,hi),threshold)=='accept'
    assert decision((lo,hi),threshold)=='undecided'
    assert decision((Q//2,Q//2),Fraction(1,2))=='accept'
    exact_tie=[dict(roi_index=9,bounds=(Q//2,Q//2)),dict(roi_index=2,bounds=(Q//2,Q//2))]
    identical=[dict(roi_index=9,bounds=(10,20),signature=b'same'),dict(roi_index=2,bounds=(10,20),signature=b'same')]
    overlap=[dict(roi_index=9,bounds=(10,20)),dict(roi_index=2,bounds=(19,21))]
    separated=[dict(roi_index=9,bounds=(10,20)),dict(roi_index=2,bounds=(21,30))]
    assert rank_candidates(exact_tie)['selected_roi_index']==2
    assert rank_candidates(identical)['selected_roi_index']==2
    assert rank_candidates(overlap)['status']=='undecided'
    assert rank_candidates(separated)['selected_roi_index']==2
    assert rank_candidates([])['status']=='no_candidate'
    return dict(exact_path_enumeration_cases=checks,repeated_target_15_state_exact=True,
        blank_only_empty_target_exact=True,zero_path_exact=True,threshold_tests=4,ranking_tests=5,
        overlapping_intervals_remain_undecided=True)


def main():
    if OUT.exists():raise FileExistsError(f'Preserve one Q30 validation: {OUT}')
    OUT.mkdir()
    started=time.monotonic()
    files=[Path(__file__),Path(__file__).with_name('ctc_interval.py'),
        ROOT/'docs/validation/blue-plate/char-segment/ctc-q30-plan.md',
        MODEL/'integer-config.json',MODEL/'integer-logits.npz',MODEL/'roi-predictions.json',MODEL/'selected.json',
        VAL/'integer-logits.npz',VAL/'roi-records.json',VAL/'frame-records.json',DEV/'gates.json',DEV/'config.json',
        ROOT/'tmp/blue-plate-char-segment/experiment/dev-manifest.json',
        ROOT/'tmp/blue-plate-char-segment/integer-deployment-research/tflite-softmax.h',
        ROOT/'tmp/blue-plate-char-segment/fit-gate/research/LossCTC.cu']
    sources={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in files}
    for folder in (MODEL,VAL):
        prior=read_json(folder/'delivery-freeze.json')['artifacts']
        for name,digest in sources.items():
            if name in prior:assert digest==prior[name]
    scale=Fraction.from_float(read_json(MODEL/'integer-config.json')['logit_scale'])
    tau=Fraction.from_float(STRICT_THRESHOLD)
    threshold=tau**7
    write_json(OUT/'protocol.json',dict(fraction_bits=30,oracle_fraction_bits=128,
        source_hashes=sources,scale_numerator=str(scale.numerator),scale_denominator=str(scale.denominator),
        threshold=STRICT_THRESHOLD,threshold_fitting=False,precision_search=False,
        logit_counts=dict(development=307,validation=85),image_reads=0,optimizer_steps=0,heldout_reads=0))
    certificates=[];table128=[]
    with localcontext() as context:
        context.prec=220
        for d in range(1021):
            certificate=exp_certificate(d*scale)
            certificate['difference']=d
            lo,hi=int(certificate['lower']),int(certificate['upper'])
            exact_x=Decimal((d*scale).numerator)/Decimal((d*scale).denominator)
            crosscheck=(-exact_x).exp()
            assert Decimal(lo)/Decimal(H) <= crosscheck <= Decimal(hi)/Decimal(H)
            certificates.append(certificate);table128.append((lo,hi))
    table30=[]
    for d,(lo,hi) in enumerate(table128):
        if d==0:a=b=Q
        elif d<71:
            assert lo*Q//H == hi*Q//H
            a=lo*Q//H;b=a+1
        else:a,b=0,1
        assert a*H <= lo*Q and hi*Q <= b*H
        table30.append((a,b))
    assert table128[71][1]*Q < H
    threshold_bounds=rational_bounds(threshold,30)
    assert Fraction(threshold_bounds[0],Q) <= threshold <= Fraction(threshold_bounds[1],Q)
    lut=dict(fraction_bits=30,lower=[a for a,b in table30[:71]],upper_at_zero=Q,
        upper_nonzero='lower+1',tail_start=71,tail_bounds=[0,1],supported_difference=[0,1020],
        scale_numerator=str(scale.numerator),scale_denominator=str(scale.denominator),
        tau_numerator=str(tau.numerator),tau_denominator=str(tau.denominator),
        tau_power7_numerator=str(threshold.numerator),tau_power7_denominator=str(threshold.denominator),
        tau_power7_q30_bounds=list(threshold_bounds))
    write_json(OUT/'exp-certificates.json',dict(bits=128,taylor_lower_degree=31,taylor_upper_degree=30,
        certificates=certificates,decimal_crosscheck_precision=220,proven_difference_count=1021))
    write_json(OUT/'lut.json',lut)
    write_json(OUT/'synthetic-checks.json',synthetic_checks(threshold))
    lut_hashes={n:sha(OUT/n) for n in ['exp-certificates.json','lut.json','synthetic-checks.json']}
    write_json(OUT/'lut-freeze.json',dict(artifacts=lut_hashes,frozen_before_real_logit_evaluation=True))
    print('1021 exponential bounds, exact threshold, synthetic checks and LUT freeze passed',flush=True)
    chars=read_json(DEV/'config.json')['classes'];assert len(chars)==68 and chars[-1]=='-'
    dev_manifest=read_json(ROOT/'tmp/blue-plate-char-segment/experiment/dev-manifest.json')['records']
    dev_gates=read_json(DEV/'gates.json')
    datasets=[('development',MODEL/'integer-logits.npz',read_json(MODEL/'roi-predictions.json'),dev_manifest),
              ('validation',VAL/'integer-logits.npz',read_json(VAL/'roi-records.json'),None)]
    summaries={};unresolved=[];differences=[];all_stats={};max_width=0
    for dataset,path,predictions,manifest in datasets:
        data=np.load(path)['logits'];expected=307 if dataset=='development' else 85
        assert data.shape==(expected,68,18) and data.dtype==np.int16
        assert len(predictions)==expected and int(data.min())>=-764 and int(data.max())<=256
        runtime=[];records=[]
        for i,(x,prior) in enumerate(zip(data,predictions)):
            greedy=x.argmax(axis=0).tolist();target=collapse(greedy,67)
            assert target==prior['decoded_ids'] and ''.join(chars[c] for c in target)==prior['code']
            assert bool(grammar(prior['code']))==prior['legal']
            distances=(x.max(axis=0).astype(np.int32)[None]-x.astype(np.int32)).T
            bounds=ctc_bounds(emissions(distances,table30,30,all_stats),target,30,stats=all_stats)
            oracle=ctc_bounds(emissions(distances,table128,128),target,128)
            encloses=bounds[0]*H <= oracle[0]*Q and oracle[1]*Q <= bounds[1]*H
            float_probability=math.exp(prior['sequence_log_probability'])
            float_inside=Fraction(bounds[0],Q) <= Fraction.from_float(float_probability) <= Fraction(bounds[1],Q)
            raw_status=decision(bounds,threshold)
            float_status='accept' if prior['score'] is not None and prior['score']>=STRICT_THRESHOLD else 'reject'
            status=raw_status if prior['legal'] else 'grammar_reject'
            meta=manifest[i] if manifest is not None else prior
            sample=meta['sample_index'];label=meta['source_transcript'] if manifest is not None else prior['label']
            combined=dev_gates[i]['combined_pass'] if manifest is not None else prior['combined_pass']
            row=dict(roi_index=i,sample_index=sample,label=label,code=prior['code'],legal=prior['legal'],
                decoded_ids=target,dp_state_count=2*len(target)+1,combined_pass=combined,
                probability_lower_q30=bounds[0],probability_upper_q30=bounds[1],
                probability_lower=bounds[0]/Q,probability_upper=bounds[1]/Q,
                probability_width_q30=bounds[1]-bounds[0],reference_lower_q128=str(oracle[0]),reference_upper_q128=str(oracle[1]),
                contains_proven_reference=encloses,float_probability=float_probability,float_probability_inside=float_inside,
                frozen_float_score=prior['score'],float_threshold_status=float_status,raw_interval_status=raw_status,
                acceptance_status=status,hardware_15_state_eligible=bool(prior['legal']))
            records.append(row)
            runtime.append(dict(**row,bounds=bounds,signature=(x.tobytes(),tuple(target))))
            max_width=max(max_width,bounds[1]-bounds[0])
            if status=='undecided':unresolved.append(dict(dataset=dataset,kind='roi_threshold',roi_index=i,bounds=bounds))
            if not encloses or not float_inside or (prior['legal'] and status!='undecided' and status!=float_status):
                differences.append(dict(dataset=dataset,kind='roi_probability_or_acceptance',roi_index=i,record=row))
        write_json(OUT/f'{dataset}-roi-intervals.json',records)
        if dataset=='development':
            frozen_selected=read_json(MODEL/'selected.json')
            baseline={mode:{r['sample_index']:r for r in rows} for mode,rows in frozen_selected.items()}
        else:
            baseline={mode:{r['sample_index']:r['methods'][mode+'_strict'] for r in read_json(VAL/'frame-records.json')}
                      for mode in ['ocr_only','combined']}
        groups=defaultdict(list)
        for row in runtime:groups[row['sample_index']].append(row)
        frames=[];counts={};ranking_counts={}
        for mode in ['ocr_only','combined']:
            tally=Counter();ranks=Counter()
            for sample,rows in groups.items():
                legal=[r for r in rows if r['legal'] and (mode=='ocr_only' or r['combined_pass'])]
                ranking=rank_candidates(legal);ranks[ranking['status']]+=1
                winner=next((r for r in legal if r['roi_index']==ranking['selected_roi_index']),None)
                state='reject' if ranking['status']=='no_candidate' else 'undecided' if ranking['status']=='undecided' else winner['acceptance_status']
                code=winner['code'] if state=='accept' else None
                outcome='undecided' if state=='undecided' else 'rejected' if code is None else 'correct' if code==rows[0]['label'] else 'wrong'
                tally[outcome]+=1
                old=baseline[mode][sample]
                old_roi=old['roi_index'] if dataset=='development' else old['selected_roi_index']
                old_accept=old['score'] is not None and old['score']>=STRICT_THRESHOLD
                old_code=old['code'] if old_accept else None
                entry=dict(sample_index=sample,mode=mode,label=rows[0]['label'],ranking=ranking,
                    acceptance_status=state,code=code,outcome=outcome,frozen_selected_roi=old_roi,frozen_accepted_code=old_code,
                    selection_matches=ranking['status']!='undecided' and ranking['selected_roi_index']==old_roi,
                    acceptance_matches=state!='undecided' and code==old_code)
                frames.append(entry)
                if state=='undecided':unresolved.append(dict(dataset=dataset,kind='frame_selection_or_threshold',**entry))
                if (ranking['status']!='undecided' and not entry['selection_matches']) or (state!='undecided' and not entry['acceptance_matches']):
                    differences.append(dict(dataset=dataset,kind='frame_difference',**entry))
            counts[mode]=dict(total=len(groups),**{k:tally[k] for k in ['correct','wrong','rejected','undecided']})
            ranking_counts[mode]=dict(ranks)
        write_json(OUT/f'{dataset}-frame-comparison.json',frames)
        summaries[dataset]=dict(rois=expected,legal_rois=sum(r['legal'] for r in records),
            proven_reference_contained=sum(r['contains_proven_reference'] for r in records),
            float_probability_contained=sum(r['float_probability_inside'] for r in records),
            roi_threshold_undecided=sum(r['acceptance_status']=='undecided' for r in records),
            counts=counts,ranking_counts=ranking_counts,
            max_probability_width_q30=max(r['probability_width_q30'] for r in records),
            max_legal_probability_width_q30=max(r['probability_width_q30'] for r in records if r['legal']))
        print(dataset,summaries[dataset],flush=True)
    assert all(sha(ROOT/n)==h for n,h in sources.items())
    assert all(sha(OUT/n)==h for n,h in lut_hashes.items())
    assert all_stats['softmax_sum_bits']<=37 and all_stats['softmax_numerator_bits']<=61
    assert all_stats['dp_sum_bits']<=32 and all_stats['dp_product_bits']<=62
    write_json(OUT/'unresolved.json',unresolved);write_json(OUT/'differences.json',differences)
    result=dict(status='PASS_FROZEN_LOGITS' if not unresolved and not differences else 'UNRESOLVED_OR_DIFFERENT',
        summaries=summaries,unresolved_records=len(unresolved),difference_records=len(differences),
        max_probability_width_q30=max_width,max_probability_width=max_width/Q,measured_integer_widths=all_stats,
        exponential_difference_proofs=1021,fixed_q30_lut_bytes=71*4,threshold_exact_rational=True,
        elapsed_seconds=time.monotonic()-started,image_reads=0,network_inference_runs=0,optimizer_steps=0,heldout_reads=0,
        input_files_unchanged=True,lut_unchanged=True,precision_search=False,hardware_rtl_pass=False)
    write_json(OUT/'results.json',result)
    write_json(OUT/'frozen.json',dict(artifacts={p.name:sha(p) for p in OUT.iterdir() if p.is_file()}))
    print(result,flush=True)


if __name__=='__main__':main()
