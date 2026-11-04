# Live hosting on this Windows Server

Public URL: https://badabhai.shreejientserv.in

## What is running
- **Nginx** (`RidersHub-Nginx`) terminates TLS (Let's Encrypt friendly name **BadaBhai**) and proxies to Uvicorn on `127.0.0.1:8000`. This host does **not** use IIS for BadaBhai.
- App service: `BadaBhaiAPI` (NSSM, Automatic, `LocalSystem`) with `PREWARM_VOICES=1`
- Config: `C:\nginx\conf\badabhai.conf` (repo copy under `deploy\nginx\badabhai.conf`)
- Public `/operator/archive` and `/api/private/*` return 403 from Nginx; on the server use `http://127.0.0.1:8000/operator/archive`
- AI crawlers (Meta agent UAs) get the landing page **without Scrimba iframes** (links kept) because embedded third-party players often make their browser report `/` as unreachable

## Useful commands
```powershell
& C:\nssm\win64\nssm.exe status BadaBhaiAPI
Restart-Service BadaBhaiAPI
Restart-Service RidersHub-Nginx
curl.exe -s https://badabhai.shreejientserv.in/health
```

## Voice / Meta
- MMS models cache: `C:\Dev\BadaBhai\.cache\huggingface`
- `CALL_MODE=meta`, `META_REASONING_EFFORT=low`
- Prewarm caches welcome/capabilities audio so the first spoken greeting is fast

## Exotel
Private Voicebot WSS URL is in `exotel-url.txt` (not for Git). Paste that into Exotel for `badabhai.shreejientserv.in`.

## Archive / Exotel API
- Calls are not stored. Postgres is not used by the live demo.
- `EXOTEL_API_BASE_URL=https://api.exotel.com` (account API returns 401 on `api.in.exotel.com` with these credentials)
- Public archive routes remain 403 on Nginx; local archive: `http://127.0.0.1:8000/operator/archive` with `X-IIS-User`

## Meta.ai site review
The public site is reachable over the internet (DNS `103.180.236.49`, HTTPS GET/HEAD 200). If Meta.ai says it cannot open the page, that is usually Meta’s managed browser/policy limit, not an outage on this host. Judges should open the URL in a normal browser.
