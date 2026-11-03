# Windows Server 2022 deployment

Target: 4 CPU cores, 16 GB RAM, no GPU. Start with **one simultaneous call** and measure CPU/RAM and reply latency. No GPU is required by this CPU-based prototype. Capacity is not load-tested.

The app must run continuously; Cursor/Codex do not need to stay open. Codex is a development assistant, not a component of the telephone runtime.

## 1. Clone and prepare

Install 64-bit Python 3.11 and Git on the server. Use one dedicated Windows account for setup and execution, so the model cache is shared. In PowerShell:

```powershell
git clone https://github.com/naimishkathrani-web/BadaBhai.git D:\Apps\BadaBhai
cd D:\Apps\BadaBhai
.\deploy\setup.ps1
```

The first install downloads packages and both Meta voice models. Setup creates a private `.env` with a random app token. Add the dev.meta.ai key after `MODEL_API_KEY=`. Do not put keys in `.env.example`. For an existing clone use `git pull --ff-only`; do not copy a laptop `.venv` to the server.

Run setup under the same account that will host the app. Use `.venv\Scripts\python.exe -m pytest -q` to verify the installation.

## 2. First local run

```powershell
.\start.ps1
```

Wait for `Voice startup complete: ready to accept calls` in the console before testing. Open http://127.0.0.1:8000, use the private APP_TOKEN, and test Hindi and English replies and playback. Initial startup can take time; later calls reuse the loaded voices.

The home page is also the live call dashboard. Enter the APP_TOKEN and select **Connect dashboard** before placing an Exotel test call. The transcript, language, source reference and per-turn timing appear live. The server does not persist call events; the operator's browser keeps the visible transcript until the next call or page close. Treat the page and APP_TOKEN as operator-only; use HTTPS on a public hostname.

### Optional opt-in SMS recap

The caller can press **3 after PM-KISAN guidance** to request the official portal link by SMS. The app sends only after that keypress and uses the inbound caller number supplied by Exotel in the call start event. SMS is disabled until the server's private `.env` contains `EXOTEL_SMS_BASE_URL`, `EXOTEL_API_KEY`, `EXOTEL_API_TOKEN`, `EXOTEL_ACCOUNT_SID`, `EXOTEL_SMS_FROM`, `EXOTEL_DLT_ENTITY_ID`, and approved `EXOTEL_DLT_TEMPLATE_HI` / `EXOTEL_DLT_TEMPLATE_EN` values. Exotel requires approved DLT registration and sender/template configuration for Indian traffic. Check the received SMS on a real phone before showing this feature as working; HTTP acceptance does not confirm delivery. Do not commit these values.

## 3. Permanent public hostname

Recommended address: `badabhai.shreejientserv.in` (proposed, not configured). The parent domain currently has dns-parking.com nameservers. A standard Cloudflare published-application tunnel needs an appropriately configured Cloudflare DNS zone. **Do not casually change nameservers**: inventory and preserve existing website, email MX, SPF/DKIM/DMARC, verification, and other DNS records before a migration.

Options:

1. Configure the domain/DNS for a **named Cloudflare Tunnel**, create a public hostname mapping to `http://127.0.0.1:8000`, and install its connector as a Windows service using the account-specific command from Cloudflare. No inbound port-forwarding is needed for this route. The connector token stays private on the server.
2. Keep current DNS and use a reverse proxy on the server with a valid TLS certificate and WebSocket support, plus a DNS record pointing to the server's reachable public address. This requires deliberate firewall/NAT/port 443 configuration. Never expose the bare port 8000 to the internet.

The appropriate option depends on domain control, current DNS records, public IP and firewall access. Neither has been configured remotely by this repository. The current random trycloudflare URL is for testing, not dependable judging uptime.

Once the permanent hostname works:

```powershell
.\.venv\Scripts\python.exe deploy\write-exotel-url.py badabhai.shreejientserv.in
```

Copy the entire line from the private `exotel-url.txt` into Exotel **Voicebot URL**, save, and make a real call. The URL uses a path token because query-token authentication failed in this trial account. A stable hostname survives app restarts and later server moves if DNS/tunnel routing and APP_TOKEN remain the same. Moving from the laptop's temporary hostname requires changing Exotel's URL once.

## 4. Run automatically after reboot

After manual testing, stop the manual `start.ps1` process. In Windows Task Scheduler create a task under the **same account used for setup**:

- Trigger: At startup; allow a short startup/network delay.
- Action program: `powershell.exe`.
- Arguments: `-NoProfile -File "D:\Apps\BadaBhai\deploy\run-server.ps1"`.
- Start in: `D:\Apps\BadaBhai`.
- Choose Run whether user is logged on or not, and supply that account's credentials yourself.
- Remove the default execution-time cutoff; enable restart on failure and prevent duplicate instances.

The supervisor script restarts the Python app after unexpected exits and writes timestamped ignored log files. Configure log retention on the server. Keep exactly one app instance: voice models and per-call state are in memory. Configure the named Cloudflare connector separately as a Windows service. Reboot and verify an external call without opening Cursor/Codex.

## 5. Continue development on the server

Open `D:\Apps\BadaBhai` in Cursor, optionally with the official Codex IDE extension. Or install Codex CLI (`npm install -g @openai/codex` with Node.js installed), run `codex` in the project directory and sign in. Windows Server compatibility of the chosen developer tool must be checked during installation.

Read `HANDOFF.md` first. This chat does not automatically gain access to the server or transfer its live state. Never send Windows passwords, Meta keys or tunnel tokens in chat. The deployed app still uses Meta models, regardless of which coding assistant maintains it.

## 6. Known gaps before wider use

- Text now streams into sentence-sized synthesis jobs; later synthesis overlaps playback. Press 9 to interrupt and clear playback. Speech-triggered interruption and echo-aware full duplex are still future work.
- Default capacity is one simultaneous call (MAX_CONCURRENT_CALLS). Tune endpointing and measure latency before calling this a natural realtime assistant. Minimal reasoning is the default; harder questions may need more reasoning.
- Use timestamps/timing logs to distinguish recognition, Meta inference and speech generation delays. Short replies and preloaded voices reduce waiting, but are not a latency guarantee.
- Test trial expiry, Exotel AgentStream pricing/activation, Meta billing limits and restart recovery.
- MMS has noncommercial license restrictions. Review rights before offering a commercial product.

References: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/windows/ and https://developers.openai.com/codex/ide
