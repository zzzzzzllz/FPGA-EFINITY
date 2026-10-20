"""Fixed Q8 BGR LPRNet entry point; no threshold fitting or training."""
import ast
import importlib.util

import numpy as np
import torch

from pretrained_new_rois import PUBLIC, decode, resize_q8, sha

STRICT_THRESHOLD = 0.9931710550839266
COMPARISON_THRESHOLD = 0.9386077887914179


class FixedLPRNet:
    """Load once, then call with one uint8 BGR crop of shape (64, 224, 3)."""

    def __init__(self):
        expected = {
            'model/LPRNet.py': '94a49696268ff942d92d58285ddeacab9b2ef35a4102bd73862518729e0dfc14',
            'data/load_data.py': 'a00ffd27459414a1244dd8205876d25c14677d1368537399e1f6c4d124bcf83a',
            'weights/Final_LPRNet_model.pth': 'd1ca22ca7a251a90702a166c8ad8ce7f05acb39f5ef8055139a33d462716d1ad',
        }
        for name, digest in expected.items():
            if sha(PUBLIC/name) != digest:
                raise ValueError(f'Frozen LPRNet source changed: {name}')
        tree = ast.parse((PUBLIC/'data/load_data.py').read_text(encoding='utf8'))
        self.chars = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'CHARS' for t in n.targets)))
        if len(self.chars) != 68 or self.chars[-3:] != ['I', 'O', '-']:
            raise ValueError('Expected the original 68-class alphabet and blank67')
        spec = importlib.util.spec_from_file_location('fixed_public_lprnet', PUBLIC/'model/LPRNet.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.net = module.build_lprnet(lpr_max_len=7, phase=False, class_num=68, dropout_rate=0)
        self.net.load_state_dict(torch.load(PUBLIC/'weights/Final_LPRNet_model.pth',
                                          map_location='cpu', weights_only=True), strict=True)
        self.net.eval()
        self.net.requires_grad_(False)

    @torch.inference_mode()
    def __call__(self, roi_bgr):
        if not isinstance(roi_bgr, np.ndarray) or roi_bgr.dtype != np.uint8 or roi_bgr.shape != (64, 224, 3):
            raise ValueError('Expected one uint8 BGR ROI with shape (64, 224, 3)')
        if self.net.training:
            raise ValueError('Fixed LPRNet must remain in eval mode')
        resized = resize_q8(roi_bgr, 24, 94)
        x = (resized.astype(np.float32)-127.5)*0.0078125
        logits = self.net(torch.from_numpy(x.transpose(2, 0, 1).copy())[None])[0]
        if logits.shape != (68, 18) or not torch.isfinite(logits).all():
            raise ValueError('Invalid LPRNet logits')
        result = decode(logits, self.chars)
        result['strict_accepts'] = result['legal'] and result['score'] >= STRICT_THRESHOLD
        result['comparison_accepts'] = result['legal'] and result['score'] >= COMPARISON_THRESHOLD
        result['logits'] = logits.numpy().copy()
        return result
