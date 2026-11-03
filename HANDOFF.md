# Handoff for continuing on Windows Server

Read `README.md`, `DEPLOY_WINDOWS.md` and `HACKATHON.md` before changes. Do not expose or commit `.env`, exotel-url.txt, logs, caller information, model cache, binaries or a virtual environment.

## Current verified state

- Incoming Exotel calls work on the development machine, including real caller questions and Meta spoken replies (participant confirmed).
- Meta API key lives only in local `.env`; server needs its own private copy/configuration.
- Meta `muse-spark-1.3` answers; `muse-voice-transcribe-1.0` recognizes speech; local Meta MMS Hindi and English synthesize audio.
- No model switch required by the participant guide. `meta-models/muse-spark-open-1026` applies specifically to Baseten; that needs separate Baseten credentials and is relevant to the optional open-weight bonus.
- Call flow: Call Start → Voicebot → Hangup. Normal Exotel number, not toll-free. No Vi SIM/forwarding required.
- Current public hostname is an expiring laptop tunnel, kept out of Git. Replace with a stable server hostname and update Exotel after validation.
- Eleven automated tests and simulated live Meta phone pipelines have passed before deployment preparation. Run the suite again after changes.

## Failure fixes already made

- Authentication now accepts `/exotel/{APP_TOKEN}` as well as legacy query auth. Use path format in Exotel.
- Both voices and welcomes load before accepting calls when PREWARM_VOICES=1. Cold loading during a call previously caused silence/disconnects.
- Local MMS uses cached models by default; `scripts.warmup` downloads them first.
- Meta answers use low reasoning effort and 1500 token allowance; empty/failed answer turns speak a retry prompt and preserve the call.
- Keypresses during welcome playback are queued rather than discarded.

## Immediate next work

1. Follow Windows deployment steps and establish a permanent TLS/WebSocket hostname.
2. Test a real Hindi and English multi-turn call on the server and after reboot.
3. Improve reply latency: measure ASR boundary delay, Meta inference and MMS synthesis, then introduce first-sentence streaming and tune CPU use. Never silently swap to a non-Meta model.
4. Add appropriate call concurrency limits before a public demo with multiple callers; global synthesis currently serializes voice generation.
5. Complete the public demo/video/submission checklist. Deadline from supplied guide: 4 Nov 2026 9 PM EST = 5 Nov 2026 7:30 AM IST. Submission and personal acceptance/waiver are user actions.

Stay honest in the demo: basic-phone AI access is working; worldwide toll-free access and full-duplex conversation are future work. Respect banned project categories in the guide and model/data licenses.
