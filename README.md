# BadaBhai

BadaBhai is voice-first AI guidance on an ordinary phone. No app is required. A caller dials, asks in Hindi or English, and hears a short spoken answer.

Live demo: [https://badabhai.shreejientserv.in](https://badabhai.shreejientserv.in)

The application code is under the MIT License. See [LICENSE](LICENSE). Meta's API and the optional MMS voice models keep their own terms.

## Try the demo

- Open [Live Desk](https://badabhai.shreejientserv.in/dashboard), then call **+91 79 4850 4917**. From a US landline, dial **011 91 79 4850 4917**.
- India numbers start in Hindi. Other numbers start in English.
- Press **1** for what the call can do, **2** for English, **3** for Hindi, or **9** to interrupt. Speaking over an answer also interrupts it.
- Words, language, and timings appear only while the call is open. The phone number stays hidden. Nothing from the call is saved.
- One call at a time. The free Exotel line ends after about three and a half minutes, so ask early. It is not toll-free. If the line is down, open [/backup-demo](https://badabhai.shreejientserv.in/backup-demo). The trial number may stop around 9 November 2026.

## What a judge should open

- [/](https://badabhai.shreejientserv.in/) — the idea, the 90-second walkthrough, and the phone number.
- [/how-it-works](https://badabhai.shreejientserv.in/how-it-works) — the proof of concept that runs today.
- [/future#impact](https://badabhai.shreejientserv.in/future#impact) — what we would build next, starting with nearby public job posts. That helper is not on the call today.
- [/commitment](https://badabhai.shreejientserv.in/commitment) — if this wins any prize, half goes to a Rajkot and Ahmedabad pilot, official-source scheme explainers, and MCA and BTech interns.
- [/architecture](https://badabhai.shreejientserv.in/architecture) — how the call is built with Meta.

This is an independent prototype, not a Meta product and not a government service. It does not decide eligibility and it does not ask for Aadhaar, an OTP, or account details.

## Models

- Hearing: Meta `muse-voice-transcribe-1.0`, biased to Hindi and English.
- Answers: Meta `muse-spark-1.3`. Everyday questions stay short. A public office, address, or phone number uses the same model with Meta web search, and the voice says only what that search found.
- Speech: an Indian voice speaks the answer on the phone line. Meta MMS Hindi and English models are an optional local fallback and stay under CC-BY-NC-4.0.

Jobs, more Indian languages, scheme explainers, village orders, and live translation are next steps. They are not features of the live call. Today's call is Hindi and English only.

## Run it locally

Use Python 3.11 or 3.12.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
Copy-Item .env.example .env
```

Put `MODEL_API_KEY` and a long random `APP_TOKEN` in `.env`. Keep `.env` out of Git. The phone connection uses the Voicebot URL from `deploy/write-exotel-url.py`. Keep that URL private.

```powershell
.\.venv\Scripts\python.exe -m scripts.warmup
.\start.ps1
```

Open `http://127.0.0.1:8000`. The public site on this project is Nginx in front of one Uvicorn process, because the call state stays in memory. One call at a time.

Deployment notes are in [DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md). Demo boundaries are in [HACKATHON.md](HACKATHON.md). Third-party terms are in [THIRD_PARTY.md](THIRD_PARTY.md).
