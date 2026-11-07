# Hosting research, 3 November 2026

No verified unlimited, always-on free GPU server was found for this telephone service. A free GPU allocation is different from dependable continuous phone hosting. Confirm account eligibility, quotas and billing before activation.

| Option | What is advertised | Relevance |
|---|---|---|
| Modal Starter | $30 monthly compute credits, GPU execution billed by use | A limited demo may fit in credits. Not unlimited free hosting. Cold starts and persistent-container charges must be considered. The participant guide also mentions discretionary $100 partner credits. |
| Hugging Face ZeroGPU | Shared GPU capacity dynamically allocated to supported Spaces | Useful for compatible demos. Quotas, scheduling and Gradio integration make it unsuitable as a drop-in always-on GPU WebSocket server for the current app. |
| Lightning AI | Free CPU Studio and eligible GPU credits/demo allowances | GPU free usage is capped; demo auto-sleep/auto-start affects first-call latency. Verify current account allowances. |
| Existing Windows Server 2022 | Participant-owned 4-core CPU, 16 GB RAM | Recommended immediate demo host. No new GPU account needed; Meta inference/ASR stay hosted and only MMS synthesis runs locally. Measure real performance. |

Sources:

- https://modal.com/pricing
- https://huggingface.co/docs/hub/spaces-zerogpu
- https://lightning.ai/docs/platform/overview/faq/billing
- https://code.lightning.ai/docs/platform/build/host-web-apps/host-demos/

## Performance decisions

The existing Muse Wonder model runs in Meta's cloud, not on the laptop. A local GPU would accelerate local speech synthesis, not remove Meta/network/ASR latency. No sub-800 ms total-loop performance is promised.

Implemented: minimal reasoning, direct short answers, text streaming into bounded sentence buffers, synthesis/playback overlap, preloaded voices, three recognition reconnect attempts, press-9 playback clearing and generation cancellation, and one simultaneous call by default.

MMS still generates each sentence's waveform before that sentence is packetized. This is not native streaming speech synthesis or a full-duplex speech-to-speech model. Packetizing a complete waveform into smaller chunks alone does not remove the time spent generating it.

Exotel specifies 3200–100000-byte chunks in multiples of 320. At 8 kHz mono 16-bit PCM, 3200 bytes represents 200 ms, so blindly forcing 100 ms would fall below that documented minimum. Current packet sizing preserves the minimum. Source: https://developer.exotel.com/docs/agentstream/websocket-protocol

Training audio-token adapters or reproducing Voicebox/Audiobox is a separate research effort requiring data, compute, training and evaluation. Adding codec tokens alone does not create a trained conversational speech model. It is not the chosen hackathon implementation path.
