"""Private 30-day call archive using the PostgreSQL command-line client.

No database driver is added to the application. Install psql on the server and
configure the standard PG* environment variables in the service environment.
"""
import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

log = logging.getLogger('badabhai.archive')

SCHEMA = """
CREATE TABLE IF NOT EXISTS badabhai_calls (
  call_sid text PRIMARY KEY,
  caller_number text,
  started_at timestamptz NOT NULL,
  ended_at timestamptz NOT NULL,
  language text,
  transcript jsonb NOT NULL DEFAULT '[]'::jsonb,
  recording bytea,
  recording_content_type text,
  duration_seconds integer,
  usefulness text,
  saved_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE badabhai_calls ADD COLUMN IF NOT EXISTS usefulness text;
CREATE INDEX IF NOT EXISTS badabhai_calls_caller_date_idx
  ON badabhai_calls (caller_number, started_at DESC);
CREATE INDEX IF NOT EXISTS badabhai_calls_date_idx
  ON badabhai_calls (started_at DESC);
"""


def _b64(value):
    return base64.b64encode(value if isinstance(value, bytes) else str(value).encode('utf-8')).decode('ascii')


def _psql_env():
    env = os.environ.copy()
    env['PGCLIENTENCODING'] = 'UTF8'
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


async def _psql(sql):
    exe = os.getenv('PSQL_PATH', 'psql')
    proc = await asyncio.create_subprocess_exec(
        exe, '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-f', '-',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE, env=_psql_env(),
    )
    # subprocess inherits PGHOST/PGUSER/PGPASSWORD etc from the app service.
    try:
        _, err = await asyncio.wait_for(proc.communicate(sql.encode('utf-8')), timeout=90)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError('PostgreSQL write timed out') from None
    if proc.returncode:
        # Never emit connection strings, credentials or SQL values to logs.
        raise RuntimeError('PostgreSQL command failed (' + str(proc.returncode) + '): ' + err.decode(errors='replace')[-500:])


async def _psql_json(sql):
    # Pass SQL on stdin (not -c) so Windows shell code pages cannot corrupt Unicode.
    proc = await asyncio.create_subprocess_exec(
        os.getenv('PSQL_PATH', 'psql'), '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-f', '-',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=_psql_env(),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(sql.encode('utf-8')), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError('PostgreSQL query timed out') from None
    if proc.returncode:
        raise RuntimeError('PostgreSQL query failed (' + str(proc.returncode) + '): ' + err.decode(errors='replace')[-500:])
    return json.loads(out.decode('utf-8-sig').strip() or 'null')


async def list_calls(search='', limit=100):
    encoded = _b64(search.strip())
    take = max(1, min(250, int(limit)))
    return await _psql_json(f"""
SELECT COALESCE(json_agg(row_to_json(c)), '[]'::json)
FROM (
  SELECT call_sid, CASE WHEN caller_number IS NULL THEN 'Unknown'
    ELSE '**** ' || right(caller_number, 4) END AS caller,
    started_at, ended_at, language, duration_seconds, usefulness,
    (recording IS NOT NULL) AS has_recording,
    jsonb_array_length(transcript) AS turns
  FROM badabhai_calls
  WHERE convert_from(decode('{encoded}','base64'),'UTF8') = ''
     OR caller_number ILIKE '%' || convert_from(decode('{encoded}','base64'),'UTF8') || '%'
     OR call_sid ILIKE '%' || convert_from(decode('{encoded}','base64'),'UTF8') || '%'
  ORDER BY started_at DESC LIMIT {take}
) c;
""") or []


async def get_call(call_sid, include_recording=False):
    encoded = _b64(call_sid)
    recording_field = ("CASE WHEN recording IS NULL THEN NULL ELSE replace(encode(recording, 'base64'), E'\\n', '') END"
                       if include_recording else 'NULL')
    return await _psql_json(f"""
SELECT row_to_json(c)
FROM (
  SELECT call_sid, CASE WHEN caller_number IS NULL THEN 'Unknown'
    ELSE '**** ' || right(caller_number, 4) END AS caller,
    started_at, ended_at, language, duration_seconds, usefulness,
    recording_content_type, transcript,
    {recording_field} AS recording_base64
  FROM badabhai_calls
  WHERE call_sid = convert_from(decode('{encoded}','base64'),'UTF8')
) c;
""")


async def initialize():
    """Create the archive table and enforce retention at service startup."""
    if not os.getenv('PGDATABASE') or not os.getenv('PGPASSWORD'):
        raise RuntimeError('PostgreSQL archive env incomplete')
    days = max(1, min(365, int(os.getenv('CALL_RETENTION_DAYS', '30'))))
    await _psql(SCHEMA + f"DELETE FROM badabhai_calls WHERE started_at < now() - make_interval(days => {days});\n")


async def save_call(*, call_sid, caller, language, started_at, transcript, usefulness):
    """Fetch the Exotel recording, then persist private call data and prune old rows."""
    if not os.getenv('PGDATABASE'):
        log.warning('Private call archive skipped: PostgreSQL is not configured')
        return
    if not call_sid:
        log.warning('Call archive skipped: Exotel did not supply a call SID')
        return
    api_key, api_token, account_sid = (os.getenv(k, '').strip() for k in
                                        ('EXOTEL_API_KEY', 'EXOTEL_API_TOKEN', 'EXOTEL_ACCOUNT_SID'))
    recording = None
    content_type = None
    duration = None
    if not (api_key and api_token and account_sid):
        log.warning('Exotel API credentials missing; saving transcript without recording')
    else:
        base = os.getenv('EXOTEL_API_BASE_URL', 'https://api.in.exotel.com').rstrip('/')
        endpoint = f"{base}/v1/Accounts/{quote(account_sid, safe='')}/Calls/{quote(str(call_sid), safe='')}.json?RecordingUrlValidity=60"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=8), auth=(api_key, api_token),
                                         follow_redirects=True) as client:
                response = await client.get(endpoint)
                response.raise_for_status()
                payload = response.json()
                call = payload.get('Call', payload.get('call', payload))
                recording_url = call.get('RecordingUrl') or call.get('recording_url')
                duration_value = call.get('Duration') or call.get('duration')
                if duration_value is not None:
                    try:
                        duration = int(float(duration_value))
                    except (ValueError, TypeError):
                        pass
                if recording_url:
                    limit = int(os.getenv('MAX_RECORDING_BYTES', str(25 * 1024 * 1024)))
                    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10), follow_redirects=True) as media_client:
                        async with media_client.stream('GET', recording_url) as audio:
                            audio.raise_for_status()
                            chunks = []
                            size = 0
                            async for chunk in audio.aiter_bytes():
                                size += len(chunk)
                                if size > limit:
                                    chunks.clear()
                                    log.warning('Recording exceeds configured archive size limit; transcript will still be saved')
                                    break
                                chunks.append(chunk)
                            else:
                                recording = b''.join(chunks)
                                content_type = audio.headers.get('content-type', 'audio/mpeg').split(';', 1)[0]
        except Exception as exc:
            log.warning('Exotel recording lookup failed (%s); saving transcript only', type(exc).__name__)

    ended = datetime.now(timezone.utc).isoformat()
    started = (started_at or datetime.now(timezone.utc)).isoformat()
    transcript_json = json.dumps(transcript, ensure_ascii=False, separators=(',', ':'))
    recording_sql = 'NULL' if recording is None else "decode('" + base64.b64encode(recording).decode('ascii') + "','base64')"
    content_sql = 'NULL' if content_type is None else "convert_from(decode('" + _b64(content_type) + "','base64'),'UTF8')"
    caller_sql = 'NULL' if not caller else "convert_from(decode('" + _b64(caller) + "','base64'),'UTF8')"
    sql = SCHEMA + f"""
INSERT INTO badabhai_calls
  (call_sid, caller_number, started_at, ended_at, language, transcript, recording, recording_content_type, duration_seconds, usefulness)
VALUES (
  convert_from(decode('{_b64(call_sid)}','base64'),'UTF8'), {caller_sql},
  convert_from(decode('{_b64(started)}','base64'),'UTF8')::timestamptz,
  convert_from(decode('{_b64(ended)}','base64'),'UTF8')::timestamptz,
  convert_from(decode('{_b64(language)}','base64'),'UTF8'),
  convert_from(decode('{_b64(transcript_json)}','base64'),'UTF8')::jsonb,
  {recording_sql}, {content_sql}, {duration if duration is not None else 'NULL'},
  {"'" + usefulness + "'" if usefulness in ('helpful', 'not_helpful') else 'NULL'}
)
ON CONFLICT (call_sid) DO UPDATE SET
  ended_at=EXCLUDED.ended_at, language=EXCLUDED.language,
  transcript=EXCLUDED.transcript,
  recording=COALESCE(EXCLUDED.recording, badabhai_calls.recording),
  recording_content_type=COALESCE(EXCLUDED.recording_content_type, badabhai_calls.recording_content_type),
  duration_seconds=COALESCE(EXCLUDED.duration_seconds, badabhai_calls.duration_seconds),
  usefulness=COALESCE(EXCLUDED.usefulness, badabhai_calls.usefulness);
DELETE FROM badabhai_calls
 WHERE started_at < now() - make_interval(days => {max(1, min(365, int(os.getenv('CALL_RETENTION_DAYS', '30'))))});
"""
    try:
        await _psql(sql)
        log.warning('Private call archive saved; recording=%s', 'yes' if recording else 'no')
    except Exception as exc:
        log.warning('Private call archive failed (%s)', type(exc).__name__)
