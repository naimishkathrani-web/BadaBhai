# BadaBhai

BadaBhai brings voice-first AI guidance to ordinary phones. The hackathon demo connects an Exotel line to Meta Muse Voice Transcribe, Muse Spark, and local Meta MMS speech. Hindi is the default for caller IDs beginning with `+91`; other callers start in English. The live demo currently supports Hindi and English.

## Judge experience

- Public landing page: `/`. `/backup-demo` is a Hindi or English walkthrough if the temporary line is unavailable.
- Public, read-only live dashboard: `/dashboard` (also available at `/operator`). It shows live turns, caller country code only, selected language, call duration, response timings, keypad interruptions, and caller usefulness feedback.
- Temporary Exotel line: **+91 79 4850 4917**. It is not toll-free or a government helpline. International access and charges depend on the caller's carrier. If the free line is down, use `/backup-demo`.

Live Desk shows the conversation only while a call is open. Calls and words are not saved. The app never asks for Aadhaar, OTPs, bank PINs, or account credentials, and it does not determine personal eligibility.

## Local setup on Windows

Use Python 3.11 or 3.12. Install the existing voice requirements and warm the local MMS models:

```powershell
cd D:\Dev\BadaBhai
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
Copy-Item .env.example .env
```

Set `MODEL_API_KEY` and a long random `APP_TOKEN` in the private `.env`. Configure the Exotel connection and, if you want private call archiving, `EXOTEL_API_BASE_URL`, `EXOTEL_API_KEY`, `EXOTEL_API_TOKEN`, `EXOTEL_ACCOUNT_SID`, and PostgreSQL `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, and `PSQL_PATH`. Keep `.env` out of Git.

Start the app with:

```powershell
.\.venv\Scripts\python.exe -m scripts.warmup
.\start.ps1
```

Open `http://127.0.0.1:8000`. The judge dashboard has no app-token prompt. `APP_TOKEN` remains server-side for the Exotel WebSocket and private internal APIs; never put it in browser code.

## PostgreSQL archive

Calls are not written to a database. Live Desk is a temporary view for the open call and clears when the call ends. PostgreSQL is not required for the demo.

Exotel supplies the call SID in its Voicebot WebSocket events. At call end, BadaBhai requests call details, downloads the signed recording URL when available, then stores the audio bytes and transcript in PostgreSQL. If Exotel API credentials are missing or the recording is unavailable, the transcript is still saved and the archive shows that no recording was captured.

The archive routes expect a trusted `X-IIS-User` header and a loopback connection. Configure IIS Windows Authentication on `/operator/archive` and `/api/private/*`; strip caller-supplied `X-IIS-User`, inject the authenticated Windows identity, and keep the Uvicorn port bound to loopback. Do not make the private API public.

## Exotel and IIS

Use the path-authenticated Voicebot URL produced by `deploy/write-exotel-url.py`; keep the app token private. For IIS, proxy HTTP and WebSocket requests to the loopback Uvicorn service, enable WebSocket forwarding, and expose `/` and `/dashboard` publicly without an app-token prompt. Protect private archive routes with Windows Authentication. Keep only one app process because call state and voice models are in memory, and the demo supports one simultaneous call.

The current number is a temporary Exotel-provided demo line. It is not toll-free or an official service. For production, use a customer-facing number approved for publication and confirm international reachability with Exotel and carriers.

## Call experience and boundaries

The caller hears a language-specific greeting and retention disclosure. Press **1** during the greeting for the capabilities overview, **2** to switch to English, and **9** to interrupt an answer. While Muse Spark is thinking, the assistant plays the soft waiting tone every four seconds. After an answer, callers can press **7** if the guidance helped or **8** if it did not.

Answers are short and general. BadaBhai expresses uncertainty about changing program rules and directs callers to an official source or office. This prototype does not yet connect each country's public-benefit information to a curated, verified knowledge base, so do not present it as an eligibility checker or government service.

## Models and limitations

- Recognition: Meta `muse-voice-transcribe-1.0` with Hindi and English language bias.
- Answer generation: Meta `muse-spark-1.3`. Ordinary questions use a short answer. Address and phone questions use the same model with Meta web search.
- Speech: local Meta MMS Hindi and English voice models.
- The phone conversation is half-duplex; speaking over an answer is not yet a reliable interrupt. Press 9 to stop playback.
- One simultaneous call by default. Measure CPU, memory, and latency before increasing capacity.
- The MMS models use CC-BY-NC-4.0 licensing. Review the license before commercial deployment.
- Future languages, government integrations, IVR replacement, village commerce, low-resource speech research, and live translation are proposals, not current features.

Windows Server deployment guidance is in [DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md). Continue work from [HANDOFF.md](HANDOFF.md), and see [HACKATHON.md](HACKATHON.md) for judge/demo positioning.
