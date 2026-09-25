import os
import threading
import time
import json
import requests
import database
from bot import run_collection
from notifier import send_report, send_text, send_commands_table

API = 'https://api.telegram.org/bot{token}/{method}'
_pending: dict[str, dict] = {}
_claim_lock = threading.Lock()

def _token() -> str:
    return os.environ.get('TG_BOT_TOKEN', '')
def _api(method: str, **payload):
    token = _token()
    r = requests.post(API.format(token=token, method=method), json=payload, timeout=40)
    r.raise_for_status()
    return r.json()
def _try_delete(chat_id: str, message_id: int) -> None:
    try:
        _api('deleteMessage', chat_id=int(chat_id), message_id=message_id)
    except Exception:
        pass
def _menu_kb() -> dict:
    rows = [[{'text': 'Claim', 'callback_data': 'menu:claim'},{'text': 'Accounts', 'callback_data': 'menu:list'}],[{'text': 'Add account', 'callback_data': 'menu:add'}]]
    app_url = os.environ.get('APP_URL', '').strip()
    if app_url:
        rows.append([{'text': 'Open app', 'web_app': {'url': app_url}}])
    return {'inline_keyboard': rows}
def _send_menu(chat_id: str) -> None:
    try:
        _api('sendMessage', chat_id=int(chat_id), text='DL Outpost menu',
             reply_markup=json.dumps(_menu_kb()))
    except Exception:
        send_text(chat_id, 'Menu: /start')
def _edit(chat_id: str, message_id: int, text: str, kb: dict = None) -> None:
    payload = {'chat_id': int(chat_id), 'message_id': message_id, 'text': text}
    if kb is not None:
        payload['reply_markup'] = json.dumps(kb)
    _api('editMessageText', **payload)
def _restore_menu_kb(chat_id: str, message_id: int) -> None:
    try:
        _api('editMessageReplyMarkup', chat_id=int(chat_id), message_id=message_id,
             reply_markup=json.dumps(_menu_kb()))
    except Exception:
        pass
def _clear_reply_keyboard(chat_id: str) -> None:
    try:
        resp = _api('sendMessage', chat_id=int(chat_id), text='\u200b',
                    reply_markup=json.dumps({'remove_keyboard': True}))
        mid = (resp.get('result') or {}).get('message_id')
        if mid:
            _try_delete(chat_id, mid)
    except Exception:
        pass
def _prompt(chat_id: str, text: str) -> None:
    state = _pending.get(chat_id)
    mid = state.get('msg_id') if state else None
    if mid:
        try:
            _edit(chat_id, mid, text)
            return
        except Exception:
            pass
    try:
        resp = _api('sendMessage', chat_id=int(chat_id), text=text)
        if state is not None:
            state['msg_id'] = (resp.get('result') or {}).get('message_id')
    except Exception:
        pass
def run_claims(accounts: list[dict], progress=print) -> None:
    if not accounts:
        return
    if not _claim_lock.acquire(blocking=False):
        progress('A collection is already running.')
        return
    try:
        by_email = {a['email']: a for a in accounts}
        def on_account(r):
            acc = by_email.get(r['email'])
            chat_id = acc['chat_id'] if acc else ''
            if r.get('remove'):
                send_report(chat_id, r['email'], None, None, error=r['error'])
                if acc:
                    database.delete_account(acc['id'])
                    progress('Removed account (no platform linked): ' + r['email'])
                return
            if r['ok']:
                send_report(chat_id, r['email'], r['reward'], r['tokens'], r.get('screenshots') or r['screenshot'])
                status = 'ok'
            else:
                send_report(chat_id, r['email'], None, None, error=r['error'])
                status = 'error'
            if acc:
                database.log_claim(acc['id'], r['reward'], r['tokens'], r['screenshot'], status)
        run_collection(accounts, progress=progress, on_account=on_account)
    finally:
        _claim_lock.release()
def _do_claim(chat_id: str) -> None:
    accs = database.get_accounts(chat_id)
    if not accs:
        send_text(chat_id, 'You have no accounts. Use the menu to add one.')
        return
    if _claim_lock.locked():
        send_text(chat_id, 'Collection is already running, please wait for it to finish.')
        return
    send_text(chat_id, f'Collecting for {len(accs)} account(s)\u2026')
    threading.Thread(target=run_claims, args=(accs,),
                     kwargs={'progress': lambda m: print(m, flush=True)}, daemon=True).start()
def _render_accounts(chat_id: str, message_id: int = None) -> None:
    accs = database.get_accounts(chat_id)
    kb_rows = []
    if accs:
        text = 'Your accounts (tap \u2715 to remove):\n' + '\n'.join(a['email'] for a in accs)
        kb_rows = [[{'text': '\u2715 ' + a['email'][:40], 'callback_data': 'rm:' + str(a['id'])}] for a in accs]
    else:
        text = 'You have no accounts. Tap Add account below.'
    kb_rows.append([{'text': '\u00ab Menu', 'callback_data': 'menu:home'}])
    kb = {'inline_keyboard': kb_rows}
    if message_id:
        try:
            _edit(chat_id, message_id, text, kb)
            return
        except Exception:
            pass
    send_text(chat_id, text, kb=json.dumps(kb))
def _parse_credentials(text: str) -> tuple[str, str] | None:
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    payload = parts[1].strip()
    spaced = payload.split(maxsplit=1)
    if len(spaced) == 2 and '@' in spaced[0]:
        return spaced[0].strip(), spaced[1]
    at = payload.find('@')
    if at < 0:
        return None
    i = at + 1
    while i < len(payload) and payload[i] not in ' \t:|':
        i += 1
    if i >= len(payload):
        return None
    email = payload[:i].strip()
    password = payload[i + 1:].strip() if payload[i] in ':|' else payload[i:].strip()
    if '@' in email and password:
        return email, password
    return None
def _save_account(chat_id: str, email: str, password: str) -> None:
    email = email.strip()
    state = _pending.get(chat_id)
    mid = state.get('msg_id') if state else None
    if '@' not in email or not password:
        _prompt(chat_id, 'Need a valid email and a password.')
        return
    try:
        action = database.upsert_account(email, password, chat_id)
    except PermissionError:
        _prompt(chat_id, 'That email is already registered by someone else.')
        if mid:
            _restore_menu_kb(chat_id, mid)
        return
    _prompt(chat_id, f'Account {action}: {email.strip().lower()}\nReports will come here.')
    if mid:
        _restore_menu_kb(chat_id, mid)
def _handle_add(chat_id: str, text: str, message_id: int) -> None:
    state = _pending.get(chat_id)
    if not state:
        creds = _parse_credentials(text)
        if creds:
            email, password = creds
            _save_account(chat_id, email, password)
            _try_delete(chat_id, message_id)
            return
        _pending[chat_id] = {'step': 'email'}
        _prompt(chat_id, 'Send the Outpost email, or use /add email:password')
        return
    if state['step'] == 'email':
        if '@' not in text:
            _prompt(chat_id, 'That is not an email. Send the Outpost email or /cancel.')
            _try_delete(chat_id, message_id)
            return
        state['email'] = text.strip()
        state['step'] = 'password'
        _prompt(chat_id, 'Send the password for ' + state['email'] + '. The message will be deleted after saving.')
        return
    if state['step'] == 'password':
        email = state['email']
        _pending.pop(chat_id, None)
        _save_account(chat_id, email, text)
        _try_delete(chat_id, message_id)
def _handle_callback(cq: dict) -> None:
    data = cq.get('data') or ''
    msg = cq.get('message') or {}
    chat_id = str((msg.get('chat') or {}).get('id') or (cq.get('from') or {}).get('id') or '')
    message_id = msg.get('message_id')
    qid = cq.get('id')
    def answer(text: str) -> None:
        try:
            _api('answerCallbackQuery', callback_query_id=qid, text=text)
        except Exception:
            pass
    if data == 'menu:claim':
        answer('Collecting')
        _do_claim(chat_id)
        return
    if data == 'menu:list':
        answer('Accounts')
        _render_accounts(chat_id, message_id)
        return
    if data == 'menu:home':
        answer('Menu')
        try:
            _edit(chat_id, message_id, 'DL Outpost menu', _menu_kb())
        except Exception:
            _send_menu(chat_id)
        return
    if data == 'menu:add':
        answer('Add account')
        state = _pending.get(chat_id) or {}
        state['step'] = 'email'
        state['msg_id'] = message_id
        _pending[chat_id] = state
        try:
            _edit(chat_id, message_id, 'Send the Outpost email, or use /add email:password')
        except Exception:
            _prompt(chat_id, 'Send the Outpost email, or use /add email:password')
        return
    if data.startswith('rm:'):
        try:
            acc_id = int(data[3:])
        except ValueError:
            answer('Error')
            return
        mine = {a['id'] for a in database.get_accounts(chat_id)}
        if acc_id not in mine:
            answer('Not your account')
            return
        database.delete_account(acc_id)
        answer('Removed')
        _render_accounts(chat_id, message_id)
        return
    answer('Unknown action')
def handle_message(msg: dict) -> None:
    chat = msg.get('chat') or {}
    if chat.get('type') not in ('private', 'group', 'supergroup'):
        return
    chat_id = str(chat['id'])
    text = (msg.get('text') or '').strip()
    if not text:
        return
    message_id = msg.get('message_id')
    cmd = text.split()[0].split('@')[0].lower()
    if cmd == '/cancel':
        state = _pending.pop(chat_id, None)
        mid = state.get('msg_id') if state else None
        if mid:
            try:
                _edit(chat_id, mid, 'Cancelled.', _menu_kb())
                _try_delete(chat_id, message_id)
                return
            except Exception:
                pass
        send_text(chat_id, 'Cancelled.')
        return
    if cmd == '/start':
        _pending.pop(chat_id, None)
        _clear_reply_keyboard(chat_id)
        send_commands_table(chat_id, [
            ('Button', 'Action'),
            ('Claim', 'collect rewards for your accounts now'),
            ('Accounts', 'your accounts (tap \u2715 to remove)'),
            ('Add account', 'add a new Outpost account'),
        ])
        _send_menu(chat_id)
        return
    if cmd.startswith('/'):
        send_text(chat_id, 'Commands are disabled. Use the menu buttons.')
        return
    if chat_id in _pending or '@' in text:
        _handle_add(chat_id, text, message_id)
        return
    send_text(chat_id, 'Use the menu buttons.')
def _poll() -> None:
    offset = 0
    print('Telegram bot polling\u2026', flush=True)
    while True:
        try:
            data = _api('getUpdates', offset=offset, timeout=30)
            for upd in data.get('result') or []:
                offset = upd['update_id'] + 1
                cq = upd.get('callback_query')
                if cq:
                    try:
                        _handle_callback(cq)
                    except Exception as e:
                        print(f'Callback error: {e}', flush=True)
                    continue
                msg = upd.get('message') or upd.get('edited_message')
                if msg:
                    handle_message(msg)
        except Exception as e:
            print(f'Telegram poll error: {e}', flush=True)
            time.sleep(3)
def _scheduler() -> None:
    hours = max(1, int(os.environ.get('CLAIM_INTERVAL_HOURS', '24')))
    print(f'Scheduler: claim all accounts every {hours}h', flush=True)
    while True:
        time.sleep(hours * 3600)
        accs = database.get_accounts()
        if not accs:
            print('Scheduler: no accounts yet', flush=True)
            continue
        print(f'Scheduler: collecting for {len(accs)} account(s)', flush=True)
        run_claims(accs, progress=lambda m: print(m, flush=True))
def _health() -> None:
    port = os.environ.get('PORT', '').strip()
    if not port:
        return
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')
        def log_message(self, *_args):
            return
    print(f'Health server on 0.0.0.0:{port}', flush=True)
    HTTPServer(('0.0.0.0', int(port)), Handler).serve_forever()
def run_bot() -> None:
    database.init_db()
    if not _token():
        raise SystemExit('Set TG_BOT_TOKEN. Users add their own accounts in Telegram with /add.')
    if os.environ.get('PORT'):
        from webapp import run_webapp
        threading.Thread(target=run_webapp, daemon=True).start()
    else:
        threading.Thread(target=_health, daemon=True).start()
    threading.Thread(target=_scheduler, daemon=True).start()
    _poll()
