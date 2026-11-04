# Windows Server 2022 deployment

Target: one Windows Server 2022 machine with 4 CPU cores and 16 GB RAM. Keep one application process and one simultaneous phone call for the judging demo. The voice models load into memory; a second worker would duplicate that cost and call state.

## 1. Pull and prepare the app

Use the existing project directory in Cursor and pull the latest `main` branch. Keep the server's `.env` private and do not copy a laptop virtual environment to the server. Install Python 3.11/3.12 and run the repository setup script if the environment has not been prepared:

```powershell
cd D:\Apps\BadaBhai
.\deploy\setup.ps1
```

Set the server `.env` values for `MODEL_API_KEY`, `APP_TOKEN`, `JUDGES_PUBLIC_PHONE_E164`, `JUDGES_PUBLIC_VIDEO_URL`, Exotel API access, and PostgreSQL. Keep current keys and app token; never display or commit them. Use the current judge line `+917948504917` and the Scrimba video links embedded in `app/landing.html`, including the scripted Hindi call reenactment backup.

Install PostgreSQL client tools and set `PSQL_PATH` to the installed `psql.exe`. Configure `PGHOST=127.0.0.1`, port, database, a restricted app user, and `PGPASSWORD` in the service environment. The app initializes `badabhai_calls` and enforces 30-day retention. Keep Postgres local/firewalled and do not use a superuser for the app.

## 2. Local service check

Start one Uvicorn instance on loopback, port 8000, using the repository's `start.ps1`/`deploy\run-server.ps1` scripts. Wait for local voice warmup to finish. Open `http://127.0.0.1:8000/`, `/dashboard`, and `/operator/archive` locally. The public dashboard no longer needs an app-token prompt. The archive must remain closed unless the trusted IIS Windows-auth header is present.

Test the audio path with a real Exotel call after the server is running: +91 callers start in Hindi; other callers start in English. Key 1 plays the capabilities overview, key 2 selects English, key 3 selects Hindi, key 9 interrupts, and keys 7/8 rate answer usefulness. The greeting discloses public live transcript visibility and private 30-day archive retention.

## 3. IIS reverse proxy and certificate

Run Uvicorn only on `127.0.0.1:8000`. Configure IIS ARR and WebSocket Protocol to proxy requests, including the Exotel `/exotel/{APP_TOKEN}` WebSocket and judge `/api/live` WebSocket. Keep `/` and `/dashboard` public and read-only. Do not put `APP_TOKEN` in browser HTML or JavaScript.

Protect `/operator/archive` and `/api/private/*` with IIS Windows Authentication. Strip any incoming `X-IIS-User` header and set it from IIS's authenticated `LOGON_USER`. Confirm the app sees IIS's loopback connection and that an unauthenticated external request cannot read recordings or transcripts. Do not expose port 8000 or PostgreSQL to the internet.

A self-signed certificate is suitable for local/internal testing. Public judges and Exotel need a certificate chain their clients trust; use a publicly trusted TLS certificate for the live hostname or verify client trust before advertising the call/dashboard. A browser certificate warning or untrusted WSS endpoint can prevent a judge from testing the service.

The DNS record, public route, IIS site binding and certificate are server-side tasks. Verify `/health`, the landing page, dashboard WebSocket, and Exotel WebSocket on the final hostname before sharing it.

## 4. Archive requirements

Completed calls are archived when Exotel provides `call_sid`, `EXOTEL_API_KEY`, `EXOTEL_API_TOKEN`, `EXOTEL_ACCOUNT_SID`, and PostgreSQL is configured. The server requests Exotel Call Details and downloads the signed recording when available; transcripts are still saved if the recording lookup fails. Confirm a real call appears in the private archive with a transcript and playable recording. Do not infer that an Exotel dashboard recording is in PostgreSQL until that check passes.

The archive UI masks caller numbers, supports filtering by full number/call ID, and opens each transcript and recording. The public live dashboard shows no full phone number. Purge is driven by `CALL_RETENTION_DAYS=30` at service startup and after completed calls.

## 5. Exotel line and product limits

The temporary judge line is `+91 79 4850 4917`. It is not toll-free and is not an official government helpline. International reachability and charges depend on Exotel account settings and the caller's carrier; confirm with a US-origin phone before making a promise. Production requires an approved public-facing number and local-language/source partnerships.

Today's voice demo supports Hindi and English. Other languages, verified government program knowledge, low-resource speech research, natural IVR replacement, village ordering, and live call translation are future proposals. MMS voice-model licensing is noncommercial CC-BY-NC-4.0; review before commercial deployment.
