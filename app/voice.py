"""Meta MMS synthesis runs locally; no non-Meta AI service is used."""
import threading
import os
from functools import lru_cache
from app.audio import Resampler

_lock = threading.Lock()


@lru_cache(maxsize=2)
def load(language):
    from transformers import AutoTokenizer, VitsModel
    model_id = 'facebook/mms-tts-hin' if language == 'hi' else 'facebook/mms-tts-eng'
    local_only = os.getenv('MMS_ALLOW_DOWNLOAD', '0') != '1'
    return (AutoTokenizer.from_pretrained(model_id, local_files_only=local_only),
            VitsModel.from_pretrained(model_id, local_files_only=local_only).eval())


@lru_cache(maxsize=64)
def synthesize(text, language, rate=8000):
    import torch
    import numpy as np
    with _lock, torch.inference_mode():
        tokenizer, model = load(language)
        inputs = tokenizer(text[:1200], return_tensors='pt')
        waveform = model(**inputs).waveform[0].cpu().numpy()
        source_rate = model.config.sampling_rate
        pcm = (np.clip(waveform, -1, 1) * 32767).astype('<i2').tobytes()
        return Resampler(source_rate, rate).convert(pcm)
