"""Telephone TTS: neural Indian voices (edge-tts) with Meta MMS fallback."""
import asyncio
import os
import re
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

from app.audio import Resampler

_lock = threading.Lock()
_FFMPEG = os.getenv('FFMPEG_PATH', 'ffmpeg')


def prepare_text(text, language):
    text = (text or '').strip()
    text = re.sub(r'[\[\]\*#_`]', '', text)
    text = text.replace('&', ' and ')
    text = re.sub(r'https?://\S+', ' link ', text)
    text = re.sub(r'\s+', ' ', text)
    for src, dst in {
        'BadaBhai': 'Bada Bhai',
        'Bada Bhai': 'Bada Bhai',
        'Aadhaar': 'Aadhaar',
        'WhatsApp': 'WhatsApp',
        'POC': 'P O C',
        'AI': 'A I',
    }.items():
        text = text.replace(src, dst)
    return text[:1200]


def edge_voice(language):
    if language == 'hi':
        return os.getenv('EDGE_HI_VOICE', 'hi-IN-MadhurNeural')
    return os.getenv('EDGE_EN_VOICE', 'en-IN-PrabhatNeural')


def _mp3_to_pcm(mp3_bytes, rate):
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as src:
        src.write(mp3_bytes)
        src_path = src.name
    out_path = src_path + '.pcm'
    try:
        subprocess.run(
            [_FFMPEG, '-y', '-i', src_path, '-ac', '1', '-ar', str(rate),
             '-f', 's16le', '-acodec', 'pcm_s16le', out_path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return Path(out_path).read_bytes()
    finally:
        for path in (src_path, out_path):
            try:
                os.unlink(path)
            except OSError:
                pass


async def _edge_mp3(text, language):
    import edge_tts
    communicate = edge_tts.Communicate(text, edge_voice(language), rate='-5%')
    chunks = []
    async for item in communicate.stream():
        if item.get('type') == 'audio':
            chunks.append(item['data'])
    if not chunks:
        raise RuntimeError('edge-tts returned no audio')
    return b''.join(chunks)


def synthesize_edge(text, language, rate=8000):
    spoken = prepare_text(text, language)
    if not spoken:
        return b''
    mp3 = asyncio.run(_edge_mp3(spoken, language))
    pcm = _mp3_to_pcm(mp3, rate)
    if not pcm:
        raise RuntimeError('ffmpeg produced empty PCM')
    return pcm


@lru_cache(maxsize=2)
def load_mms(language):
    import torch
    torch.set_num_threads(max(1, int(os.getenv('MMS_TORCH_THREADS', '4'))))
    from transformers import AutoTokenizer, VitsModel
    default_hi = 'onecxi/mms-hindi-male-indic'
    default_en = 'onecxi/mms-english-male-indic'
    model_id = os.getenv('MMS_HI_MODEL', default_hi) if language == 'hi' else os.getenv('MMS_EN_MODEL', default_en)
    local_only = os.getenv('MMS_ALLOW_DOWNLOAD', '0') != '1'
    tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=local_only)
    model = VitsModel.from_pretrained(model_id, local_files_only=local_only).eval()
    model.speaking_rate = float(os.getenv('MMS_SPEAKING_RATE', '0.90'))
    model.noise_scale = float(os.getenv('MMS_NOISE_SCALE', '0.333'))
    model.noise_scale_duration = float(os.getenv('MMS_NOISE_SCALE_DURATION', '0.333'))
    return tokenizer, model


def synthesize_mms(text, language, rate=8000):
    import torch
    import numpy as np
    from transformers import set_seed
    spoken = prepare_text(text, language)
    if not spoken:
        return b''
    with _lock, torch.inference_mode():
        tokenizer, model = load_mms(language)
        set_seed(int(os.getenv('MMS_SEED', '17')))
        inputs = tokenizer(spoken, return_tensors='pt')
        waveform = model(**inputs).waveform[0].cpu().numpy().astype(np.float32)
        peak = float(np.max(np.abs(waveform))) or 1.0
        waveform = np.clip(waveform * min(1.5, 0.98 / peak), -1.0, 1.0)
        pcm = (waveform * 32767).astype('<i2').tobytes()
        return Resampler(model.config.sampling_rate, rate).convert(pcm)


@lru_cache(maxsize=64)
def synthesize(text, language, rate=8000):
    """Prefer neural Indian edge-tts (Scrimba-like clarity); fall back to Meta MMS."""
    engine = os.getenv('TTS_ENGINE', 'edge').lower()
    if engine != 'mms':
        try:
            return synthesize_edge(text, language, rate)
        except Exception:
            if engine == 'edge':
                # Always try MMS if edge fails, unless forced edge-only.
                pass
            else:
                raise
    return synthesize_mms(text, language, rate)
