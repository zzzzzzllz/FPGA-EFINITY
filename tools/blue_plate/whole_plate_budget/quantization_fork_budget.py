"""Read-only capacity and port audit of the one tap2 quantization fork."""
from pathlib import Path
import hashlib,json,math

ROOT=Path(__file__).resolve().parents[3];DOC=ROOT/'docs/validation/blue-plate/whole-plate-budget'
paths=[ROOT/'docs/validation/blue-plate/char-segment/quantization-fork-plan.md',
    ROOT/'tools/blue_plate/char_segment/quantize_lprnet_fork.py',
    ROOT/'tools/blue_plate/char_segment/integer_lprnet_fork.py',
    ROOT/'tools/blue_plate/char_segment/quantize_lprnet.py',
    ROOT/'tmp/blue-plate-char-segment/quantization-w8a8/real-mac-vectors.json',
    DOC/'costs.json',DOC/'color-cnn-sharing.json']
hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
layers=json.loads(paths[-2].read_text())['lprnet']['layers']
layer=next(r for r in layers if r['name']=='backbone.11.block.6')
assert layer['K']==64 and layer['weights']==16384 and layer['output']==[1,256,18,44]
points=18*44;coarse=points*256;fine=points*64;capacity=262144
assert coarse+fine==253440<capacity
coverage=bytearray(coarse+fine)
for start in range(0,points,12):
    count=min(12,points-start)
    assert count*320<=4096
    # Each 8-output group forks its lanes 0 and 4 into the compact branch.
    for p in range(count):
        for group in range(32):
            for lane in range(8):
                address=(start+p)*256+group*8+lane
                coverage[address]+=1
                if lane in (0,4):
                    channel=group*8+lane
                    local_coarse=p*256+channel
                    local_fine=12*256+p*64+channel//4
                    assert local_coarse<3072 and 3072<=local_fine<3840
                    assert 256+channel//4<320
                    coverage[coarse+(start+p)*64+channel//4]+=1
assert set(coverage)=={1}
base=json.loads(paths[-1].read_text())['memory']['full_three_model_ddr_reservation']
result=dict(source_sha256=hashes,source_unchanged=all(hashlib.sha256(p.read_bytes()).hexdigest()==hashes[str(p)] for p in paths),
    slot=dict(coarse_bytes=coarse,fine_bytes=fine,total=coarse+fine,capacity=capacity,remaining=capacity-coarse-fine,
              old_input_bytes=fine,live_bytes=coarse+2*fine,pool_destination_bytes=64*16*21),
    write_block=dict(coarse=3072,fine=768,total=3840,capacity=4096,spatial_tile=12,tiles=66,byte_coverage_exact=True),
    parameters=dict(rows=320,capacity_rows=512,bytes=320*9,new_payload_bytes=64*5,new_reserved_bytes=64*9,
                    selected_lane_offsets=[0,4],secondary_row='256 + output_channel/4'),
    weight_load=dict(layer_bytes=16384,old_tiles=math.ceil(points/16),new_tiles=66,
                     old_bytes=50*16384,new_bytes=66*16384,delta_bytes=16*16384),
    extra_requantizations=fine,extra_feature_write_bytes=fine,extra_convolution_MACs=0,
    ddr=dict(previous=base,new=base+576,capacity=8*1024*1024),
    scope='No images or model evaluation; no changes to model files. Capacity passes, arithmetic/port contracts remain separate.')
assert result['source_unchanged'] and result['ddr']['new']==7015168
for directory in (DOC,ROOT/'tmp/blue-plate-whole-plate-budget'):
    (directory/'quantization-fork-budget.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='source_sha256'},indent=2))
