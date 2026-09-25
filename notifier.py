import json
import os
import requests

API = 'https://api.telegram.org/bot{token}/{method}'

def _token() -> str:
    return os.environ.get('TG_BOT_TOKEN', '')

def _post(method: str, chat_id: str, **data):
    token = _token()
    if not token or not chat_id:
        return None
    return requests.post(API.format(token=token, method=method),data={'chat_id': chat_id, **data},timeout=30)

def send_text(chat_id: str, text: str, kb=None) -> None:
    if kb is not None:
        token = _token()
        if token and chat_id:
            requests.post(API.format(token=token, method='sendMessage'),data={'chat_id': chat_id, 'text': text, 'reply_markup': kb},timeout=30)
        return
    _post('sendMessage', chat_id, text=text)

def _collect_paths(screenshot_path) -> list:
    if isinstance(screenshot_path, (list, tuple)):
        return [p for p in screenshot_path if p and os.path.exists(p)]
    if screenshot_path and os.path.exists(screenshot_path):
        return [screenshot_path]
    return []

def _post_rich(chat_id: str, payload: dict, files: dict, kb=None) -> bool:
    token = _token()
    data = {'chat_id': chat_id, 'rich_message': json.dumps(payload)}
    if kb is not None:
        data['reply_markup'] = json.dumps(kb)
    try:
        r = requests.post(API.format(token=token, method='sendRichMessage'),data=data,files=files or None,timeout=60)
        if r.ok:
            return (r.json().get('result') or {}).get('message_id')
        print('sendRichMessage failed: ' + str(r.status_code) + ' ' + r.text[:300], flush=True)
    except Exception as e:
        print('sendRichMessage error: ' + str(e)[:300], flush=True)
    return None

def _mdcell(v) -> str:
    return str(v).replace('\n', '; ').replace('|', '\\|')

def _send_rich(chat_id: str, rows: list, paths: list, header: bool = False, kb=None):
    token = _token()
    if not token or not chat_id:
        return False
    cells = []
    for idx, (k, v) in enumerate(rows):
        is_hdr = idx == 0 if header else False
        cells.append([
            {'text': str(k), 'align': 'left', 'valign': 'middle', 'is_header': is_hdr or (not header)},
            {'text': str(v), 'align': 'left', 'valign': 'middle', 'is_header': is_hdr},
        ])
    table = {'type': 'table', 'cells': cells, 'is_bordered': True, 'is_striped': True, 'is_compact': True}
    heading = {'type': 'heading', 'text': 'DL Outpost', 'size': 3}
    paths = paths[:10]
    if not paths:
        return _post_rich(chat_id, {'blocks': [heading, table]}, None, kb)
    media = []
    files = {}
    for i, p in enumerate(paths):
        mid = 'ph' + str(i)
        media.append({'id': mid, 'media': {'type': 'photo', 'media': 'attach://' + mid}})
        files[mid] = open(p, 'rb')
    try:
        lines = ['# DL Outpost', '']
        for m in media:
            lines.append('![]' + '(tg://photo?id=' + m['id'] + ')')
        lines.append('')
        lines.append('| Field | Value |')
        lines.append('| --- | --- |')
        for k, v in rows:
            lines.append('| ' + _mdcell(k) + ' | ' + _mdcell(v) + ' |')
        payload = {'markdown': '\n'.join(lines), 'media': media}
        mid = _post_rich(chat_id, payload, files, kb)
        if mid is not None:
            return mid
        for fh in files.values():
            fh.seek(0)
        blocks2 = [heading]
        for m in media:
            blocks2.append({'type': 'photo', 'photo': {'type': 'photo', 'media': m['media']['media']}})
        blocks2.append(table)
        mid = _post_rich(chat_id, {'blocks': blocks2}, files, kb)
        if mid is not None:
            return mid
    finally:
        for fh in files.values():
            fh.close()
    return None


def _send_photos_fallback(chat_id: str, paths: list, caption: str = '') -> None:
    token = _token()
    if not paths:
        return
    if len(paths) == 1:
        data = {'chat_id': chat_id}
        if caption:
            data['caption'] = caption
        with open(paths[0], 'rb') as photo:
            requests.post(API.format(token=token, method='sendPhoto'),data=data,files={'photo': photo},timeout=60)
        return
    paths = paths[:10]
    media = []
    files = {}
    for i, p in enumerate(paths):
        item = {'type': 'photo', 'media': 'attach://photo' + str(i)}
        if caption and i == 0:
            item['caption'] = caption
        media.append(item)
        files['photo' + str(i)] = open(p, 'rb')
    try:
        requests.post(API.format(token=token, method='sendMediaGroup'),data={'chat_id': chat_id, 'media': json.dumps(media)},files=files,timeout=60)
    finally:
        for fh in files.values():
            fh.close()


def send_report(chat_id,email: str,reward,tokens,screenshot_path = None,error = None) -> bool:
    chat_id = str(chat_id or os.environ.get('TG_CHAT_ID', '')).strip()
    token = _token()
    if not token or not chat_id:
        return False
    if error:
        rows = [('Account', email), ('Status', 'Error'), ('Reason', error)]
    else:
        rows = [('Account', email), ('Reward', reward), ('Tokens', tokens)]
    paths = _collect_paths(screenshot_path)
    if not paths:
        print('send_report: no screenshot files found for ' + str(email), flush=True)
    if os.environ.get('RICH_PHOTO', '') == '1' and _send_rich(chat_id, rows, paths):
        return True
    _send_photos_fallback(chat_id, paths)
    if _send_rich(chat_id, rows, []):
        return True
    send_text(chat_id, '\n'.join(str(k) + ': ' + str(v) for k, v in rows))
    return False

def send_commands_table(chat_id: str, commands: list, kb=None):
    mid = _send_rich(str(chat_id), commands, [], header=True, kb=kb)
    if mid is not None:
        return mid
    send_text(str(chat_id), '\n'.join(c + ' - ' + d for c, d in commands))
    return None
