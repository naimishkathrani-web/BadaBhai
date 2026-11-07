# Handoff for the Windows Server Cursor session

The local repository changes are pushed to `main`. Continue from the current `main` branch and read `README.md` and `DEPLOY_WINDOWS.md`. Do not copy `.env`, Exotel URLs, model keys, recordings, transcripts, caller numbers, logs, voice-model caches, or a laptop `.venv` into Git or chat.

## Current app behavior

- Exotel Voicebot streams calls to Meta Muse Voice Transcribe, Muse Wonder, and local Meta MMS Hindi/English voices.
- Caller IDs beginning in `+91` default to Hindi; other caller IDs default to English. Press 1 for what the call can do, 2 for English, 3 for Hindi, and 9 to interrupt. Speaking over an answer also interrupts.
- Live Desk at `/dashboard` shows words, country code, language, and timings only while a call is open, then clears. Phone numbers stay hidden.
- `/backup-demo` is the Hindi or English walkthrough if the temporary Exotel line +91 79 4850 4917 is unavailable.
- Calls are not saved. There is no call archive.
- Do not tell callers the call is recorded, transcribed for training, or archived.

## Before judges call

1. Keep the existing server `.env` private. Do not commit it.
2. The public site is Nginx TLS to Uvicorn on `127.0.0.1:8000`, service `BadaBhaiAPI`.
3. Place one real test call. Live Desk should show words during the call, hide the phone number, and clear when the call ends.
4. Confirm reachability from the caller's country before promising it. Carrier charges apply. This number is not toll-free. If the free line is down, send judges to `/backup-demo`.
