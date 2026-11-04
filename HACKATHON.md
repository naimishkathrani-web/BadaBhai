# Hackathon positioning and demo checklist

## Project

BadaBhai brings practical voice AI to an ordinary phone call. It demonstrates a Hindi/English Exotel bridge to Meta Muse Voice Transcribe, Muse Spark, and local Meta MMS speech. The prototype answers everyday questions, explains topics simply, can repeat key points, expresses uncertainty, and directs callers to official sources for current public-service rules.

The demo is not a government service, eligibility decision tool, or personal-account assistant. The +91 79 4850 4917 line is a temporary Exotel judging number, not toll-free. The public dashboard shows live transcript content; completed-call recordings and transcripts are private and retained for 30 days when server configuration is complete.

## Demo priorities

1. Open the landing page and play the project walkthrough and global future video. Use the clearly labeled scripted Hindi-first call reenactment at `/#call-backup` if the temporary Exotel line is unavailable; it is not a live-call recording.
2. Place a call to +91 79 4850 4917. India callers start in Hindi; other callers start in English. Press 1 for the capabilities overview; 2 for English; 3 for Hindi.
3. Ask a simple everyday question such as “Photosynthesis kya hai, simple me samjhao?” Demonstrate a short answer, a clarifying question if needed, and a repeat request.
4. Open `/dashboard` to show the live transcript, country code, language, STT finalization (`stt_ms`), Spark first text (`spark_ms`), TTS synthesis (`tts_ms`), first audio, total response time, keypad interruption, and caller rating (7/8).
5. Open `/operator/archive` only from an authenticated Windows session. Show a completed call, masked caller number, transcript and recording playback.
6. Explain the limits honestly: one simultaneous call, half-duplex phone interaction, Hindi/English only today, no verified per-country benefit database, and future language/government/IVR/commerce/translation proposals require approval, consent, trusted sources, partnerships, and evaluation.

## Impact framing

GSMA analysis estimates global annual feature-phone sales near 200 million in 2024, and a 2025 ETTelecom report attributes an approximately 54 million Indian shipment estimate to IDC. These are annual sales/shipment figures, not counts of active users. The landing page links the source material. Use exact claims with their source and year.

Potential directions include basic-phone learning, government program explanations from approved sources, natural-language enterprise IVR, voice ordering and logistics beyond cities, consent-led speech research for underrepresented languages, and live call translation. These are future opportunities, not working features or promised Meta capabilities. Do not claim that a named competitor lacks capabilities without evidence.

## Safety and data

The greeting and landing page disclose that the live transcript is publicly visible and that completed-call recordings/transcripts are privately stored for 30 days. Never present the demo as “not recording” or “not saving transcripts.” Avoid soliciting Aadhaar, OTP, bank PIN, account credentials, or other sensitive details. Keep the archive behind IIS Windows Authentication and never expose the PostgreSQL service or private recording API publicly.

## Submission

Check the organizer's current rules, eligibility, schedule, license requirements, and submission fields directly before submitting. The judge call line and a completed video do not substitute for submission or acceptance. The participant remains responsible for accepting official terms and submitting the project.
