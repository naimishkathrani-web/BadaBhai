# Models and dependencies

This repository contains application code, not model weights. Python dependency versions used in development are recorded in requirements-lock.txt. Dependencies retain their own licenses; installing them does not relicense their code under this project.

- **Meta Muse Wonder 1.0** and **Muse Voice Transcribe 1.0** are called through Meta Model API and subject to Meta's API terms and account access: https://dev.meta.ai/docs/overview
- **Meta MMS Hindi** (`facebook/mms-tts-hin`) and **Meta MMS English** (`facebook/mms-tts-eng`) are downloaded separately through Hugging Face. Model cards identify **CC-BY-NC-4.0**; this limits commercial use. https://huggingface.co/facebook/mms-tts-hin and https://huggingface.co/facebook/mms-tts-eng
- Hugging Face Transformers and PyTorch are used for local MMS inference. https://github.com/huggingface/transformers and https://github.com/pytorch/pytorch
- Exotel provides the telephone service; Cloudflare is used for development tunnel connectivity. Their software/service terms are separate from this repository.

The author must confirm appropriate rights for the intended competition distribution and any later commercial deployment. No third-party phone recordings or training datasets are distributed here.
