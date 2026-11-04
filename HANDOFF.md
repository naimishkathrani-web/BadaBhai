# Handoff for the Windows Server Cursor session

The local repository changes are pushed to `main`. Continue from the current `main` branch and read `README.md` and `DEPLOY_WINDOWS.md`. Do not copy `.env`, Exotel URLs, model keys, recordings, transcripts, caller numbers, logs, voice-model caches, or a laptop `.venv` into Git or chat.

## Current app behavior

- Exotel Voicebot streams calls to Meta Muse Voice Transcribe, Muse Spark, and local Meta MMS Hindi/English voices.
- Caller IDs beginning in `+91` default to Hindi; other caller IDs default to English. Press 2 selects English, 3 Hindi, 1 plays the capabilities overview, 9 interrupts, and 7/8 mark caller usefulness.
- The public `/dashboard` page has no access-token prompt and displays a read-only live transcript, country code only, language, turn timings, interruptions, and answer usefulness.
- The public landing page includes a current walkthrough, a future vision video, and a clearly labeled scripted call reenactment at `/#call-backup`; `/backup-demo` lets judges choose Hindi or Indian English narration if the temporary Exotel line +91 79 4850 4917 is unavailable.
- Calls are not saved. Live Desk clears when the call ends.
- Private `/operator/archive` and `/api/private/*` routes require a trusted `X-IIS-User` header and loopback request. IIS Windows Authentication must protect them, overwrite client-supplied header values, and inject the authenticated Windows identity.
- Do not tell callers the call is recorded, transcribed for training, or archived.

## Server work remaining

1. Pull current `main`, configure the existing server `.env` without revealing or replacing secrets, and update `JUDGES_PUBLIC_VIDEO_URL` to the new first walkthrough.
2. Configure `PSQL_PATH` and the dedicated PostgreSQL database role. Confirm the app can create and maintain `badabhai_calls`; keep Postgres local/firewalled.
3. Run Uvicorn as one persistent service bound to loopback. Configure IIS ARR/WebSocket for the public landing/dashboard, `/api/live`, and Exotel `/exotel/{APP_TOKEN}` route.
4. Protect the archive paths with Windows Authentication and inject the trusted IIS identity header after removing any client-provided `X-IIS-User`.
5. Use a publicly trusted TLS chain for the external hostname. Self-signed certificates are only for internal testing unless judges and Exotel are explicitly configured to trust them.
6. Place one real test call. Verify Live Desk shows words during the call, hides the phone number, and clears when the call ends. Confirm nothing is written for that call.
7. Confirm call reachability from the US before saying international calling is guaranteed. Carrier charges apply; this temporary number is not toll-free.

No DNS/server action has been performed from this local development workspace. The server owns its own `.env`, Windows service, IIS settings, and database permissions.
