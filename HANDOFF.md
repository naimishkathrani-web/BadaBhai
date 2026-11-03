# Handoff for continuing on Windows Server

Read `README.md`, `DEPLOY_WINDOWS.md` and `HACKATHON.md` before changes. Do not expose or commit `.env`, exotel-url.txt, logs, caller information, model cache, binaries or a virtual environment.

## Current verified state

- Incoming Exotel calls work on the development machine, including real caller questions and Meta spoken replies (participant confirmed).
- Meta API key lives only in local `.env`; server needs its own private copy/configuration.
- Meta `muse-spark-1.3` answers; `muse-voice-transcribe-1.0` recognizes speech; local Meta MMS Hindi and English synthesize audio.
- No model switch required by the participant guide. `meta-models/muse-spark-open-1026` applies specifically to Baseten; that needs separate Baseten credentials and is relevant to the optional open-weight bonus.
- Call flow: Call Start → Voicebot → Hangup. Normal Exotel number, not toll-free. No Vi SIM/forwarding required.
- Current public hostname is an expiring laptop tunnel, kept out of Git. Replace with a stable server hostname and update Exotel after validation.
- Twenty-two automated tests now cover sentence streaming, recognition reconnection, keypad interruption, source grounding, dashboard authentication and consent-gated SMS behavior. Run the suite again after changes.
- The judge dashboard now has a token-authenticated live view for transcript, answer, language, source and call timing. It keeps events in memory only and does not show the caller number.
- The phone and browser flows add a source-linked PM-KISAN information scenario. The caller can press 3 after the guidance to request an official-link SMS; sending requires caller consent plus Exotel and approved DLT configuration. No delivery claim is made from an API acceptance.

## Failure fixes already made

- Authentication now accepts `/exotel/{APP_TOKEN}` as well as legacy query auth. Use path format in Exotel.
- Both voices and welcomes load before accepting calls when PREWARM_VOICES=1. Cold loading during a call previously caused silence/disconnects.
- Local MMS uses cached models by default; `scripts.warmup` downloads them first.
- Meta answers use minimal reasoning effort and 1500 token allowance; empty/failed answer turns speak a retry prompt and preserve the call. Phone replies stream sentence by sentence with overlapping synthesis/playback.
- Keypresses during welcome playback are queued rather than discarded.

## Immediate next work

1. Follow Windows deployment steps and establish a permanent TLS/WebSocket hostname.
2. Test a real Hindi and English multi-turn call on the server and after reboot.
3. Measure ASR boundary finalization, first-sentence/audio delay and MMS synthesis on real Hindi and English calls. The dashboard shows speech-end to transcript-final time and final-transcript to first answer text/audio. Streaming is implemented; automatic voice interruption and echo handling remain. Never silently swap to a non-Meta model.
4. MAX_CONCURRENT_CALLS defaults to one; global synthesis serializes voice generation. Recognition streams retry up to three times. Test recovery on the final server.
5. Confirm the server's official-source context is current before the demo. To test SMS, add Exotel API credentials and approved Hindi/English DLT templates to the private server `.env`, then place a real test call and press 3 after PM-KISAN guidance. SMS is deliberately unavailable until configured.
6. Complete the public demo/video/submission checklist. Deadline from the event page: 4 Nov 2026 9 PM ET = 5 Nov 2026 7:30 AM IST. Submission and personal acceptance/waiver are user actions.

Stay honest in the demo: basic-phone AI access is working; worldwide toll-free access and full-duplex conversation are future work. Press 9 supports keypad interruption only. Respect banned project categories in the guide and model/data licenses.
