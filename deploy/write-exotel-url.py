"""Usage: python deploy/write-exotel-url.py badabhai.example.com. Never prints the token."""
import re
import sys
from pathlib import Path
from urllib.parse import quote
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
hostname = sys.argv[1] if len(sys.argv) == 2 else ''
if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', hostname) or '.' not in hostname:
    raise SystemExit('Supply a public hostname only, without https:// or a path')
token = dotenv_values(root / '.env').get('APP_TOKEN')
if not token or token == 'replace-with-a-long-random-token':
    raise SystemExit('Configure APP_TOKEN first')
(root / 'exotel-url.txt').write_text('wss://' + hostname + '/exotel/' + quote(token, safe='') + '\n')
print('Complete private Voicebot URL saved to exotel-url.txt. Do not commit or publish it.')
