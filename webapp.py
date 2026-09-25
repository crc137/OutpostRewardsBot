import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlparse
import requests as http_requests
import database
from notifier import _token

EVENT_URL = os.environ.get('EVENT_URL', 'https://outpost.dyinglightgame.com/events/dltb-1anniversary')
BASE = os.path.dirname(os.path.abspath(__file__))
_cal_cache = {'url': '', 'ts': 0.0, 'days': [], 'start': ''}
try:
    PAGE = open(os.path.join(BASE, 'index.html'), encoding='utf-8').read()
except OSError:
    PAGE = '<h1>index.html not found</h1>'

def _check_init(init_data: str):
    if not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        recv_hash = pairs.pop('hash', '')
        if not recv_hash:
            return None
        data_check = '\n'.join(k + '=' + v for k, v in sorted(pairs.items()))
        token = _token()
        if not token:
            return None
        secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv_hash):
            return None
        user = json.loads(pairs.get('user', '{}'))
        return str(user.get('id', ''))
    except Exception:
        return None

def _fetch_calendar():
    if _cal_cache['url'] == EVENT_URL and time.time() - _cal_cache['ts'] < 120 and _cal_cache['days']:
        return _cal_cache['days'], _cal_cache['start']
    html = http_requests.get(EVENT_URL, timeout=30).text
    days = []
    start = ''
    for ch in html.split('<div class="tile swiper-slide')[1:]:
        cls = ch.split('>', 1)[0]
        m_day = re.search(r'<div class="day">(\d+)</div>', ch)
        m_month = re.search(r'<div class="month[^"]*">(\w+)</div>', ch)
        m_img = re.search(r'<img src="([^"]+)" alt="([^"]*)"', ch)
        if not (m_day and m_month and m_img):
            if 'future' in cls.split() or 'closed' in ch:
                days.append({'day': '', 'month': '', 'name': '???', 'img': '', 'state': 'locked', 'gold': 'friday' in cls.split()})
            continue
        toks = cls.split()
        claimed = 'rw claimed' in ch
        if claimed:
            state = 'claimed'
        elif 'rewardClaim' in ch or 'now' in toks:
            state = 'available'
        elif 'future' in toks:
            state = 'locked'
        else:
            state = 'missed'
        src = m_img.group(1)
        if src.startswith('/'):
            src = 'https://outpost.dyinglightgame.com' + src
        days.append({'day': m_day.group(1), 'month': m_month.group(1), 'name': m_img.group(2) or 'Reward', 'img': src, 'state': state, 'gold': 'friday' in toks})
        if not start:
            try:
                mon = datetime.strptime(m_month.group(1), '%b').month
                start = f'{datetime.now().year}-{mon:02d}-{int(m_day.group(1)):02d}T00:00:00'
            except Exception:
                pass
    _cal_cache.update(url=EVENT_URL, ts=time.time(), days=days, start=start)
    return days, start

def _claimed_names(chat_id: str, since: str = '') -> list:
    q = "SELECT DISTINCT cl.reward FROM claim_log cl JOIN accounts a ON a.id = cl.account_id WHERE a.chat_id = ? AND cl.status = 'ok' AND cl.reward IS NOT NULL"
    params = [str(chat_id)]
    if since:
        q += ' AND cl.claimed_at >= ?'
        params.append(since)
    with database._conn() as conn:
        rows = conn.execute(q, params).fetchall()
    out = []
    for r in rows:
        first = (r['reward'] or '').split(';')[0].strip().lower()
        if first and 'no rewards' not in first and 'nothing claimed' not in first:
            out.append(first)
    return out

class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/health', '/healthz'):
            self._json(200, {'ok': True})
        elif path in ('/', '/index.html'):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith('/img/'):
            safe = os.path.basename(path)
            fp = os.path.join(BASE, 'img', safe)
            if os.path.isfile(fp):
                body = open(fp, 'rb').read()
                ctype = 'image/svg+xml' if safe.endswith('.svg') else ('image/jpeg' if safe.endswith('.jpg') else 'image/png')
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json(404, {'ok': False})
        elif path.startswith('/fonts/'):
            safe = os.path.basename(path)
            fp = os.path.join(BASE, 'fonts', safe)
            if os.path.isfile(fp):
                body = open(fp, 'rb').read()
                if safe.endswith('.woff2'):
                    ctype = 'font/woff2'
                elif safe.endswith('.woff'):
                    ctype = 'font/woff'
                elif safe.endswith('.ttf'):
                    ctype = 'font/ttf'
                elif safe.endswith('.eot'):
                    ctype = 'application/vnd.ms-fontobject'
                else:
                    ctype = 'application/octet-stream'
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'max-age=86400')
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json(404, {'ok': False})
        else:
            self._json(404, {'ok': False})
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get('Content-Length') or 0)
            payload = json.loads(self.rfile.read(length) or b'{}')
        except Exception:
            self._json(400, {'ok': False, 'error': 'bad json'})
            return
        chat_id = _check_init(payload.get('init_data', ''))
        if not chat_id:
            self._json(403, {'ok': False, 'error': 'bad initData'})
            return
        if path == '/api/accounts':
            accs = database.get_accounts(chat_id)
            self._json(200, {'ok': True, 'accounts': [{'email': a['email']} for a in accs]})
        elif path == '/api/add':
            email = (payload.get('email') or '').strip()
            password = payload.get('password') or ''
            if '@' not in email or not password:
                self._json(400, {'ok': False, 'error': 'need a valid email and a password'})
                return
            try:
                action = database.upsert_account(email, password, chat_id)
            except PermissionError:
                self._json(403, {'ok': False, 'error': 'that email is registered by someone else'})
                return
            self._json(200, {'ok': True, 'action': action})
        elif path == '/api/remove':
            email = (payload.get('email') or '').strip()
            if database.delete_account_by_email(email, chat_id):
                self._json(200, {'ok': True})
            else:
                self._json(404, {'ok': False, 'error': 'account not found'})
        elif path == '/api/calendar':
            try:
                days, start = _fetch_calendar()
                self._json(200, {'ok': True, 'days': days, 'claimed': _claimed_names(chat_id, start)})
            except Exception as e:
                self._json(502, {'ok': False, 'error': str(e)[:200]})
        else:
            self._json(404, {'ok': False})
    def log_message(self, *_args):
        return

def run_webapp():
    database.init_db()
    port = int(os.environ.get('PORT', '0') or 0)
    if not port:
        print('WebApp: PORT is not set, web UI disabled', flush=True)
        return
    print(f'WebApp on 0.0.0.0:{port}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
