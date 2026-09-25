import os
import sqlite3
from datetime import datetime
from crypto_utils import encrypt, decrypt

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'accounts.db')

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _migrate(conn: sqlite3.Connection) -> None:
    cols = [r['name'] for r in conn.execute('PRAGMA table_info(accounts)')]
    if 'chat_id' not in cols:
        conn.execute('ALTER TABLE accounts ADD COLUMN chat_id TEXT')

def init_db() -> None:
    with _conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_enc TEXT NOT NULL,chat_id TEXT,created_at TEXT NOT NULL)""")
        _migrate(conn)
        conn.execute("""CREATE TABLE IF NOT EXISTS claim_log(id INTEGER PRIMARY KEY AUTOINCREMENT,account_id INTEGER NOT NULL,claimed_at TEXT NOT NULL,reward TEXT,tokens TEXT,screenshot TEXT,status TEXT NOT NULL,FOREIGN KEY(account_id) REFERENCES accounts(id))""")

def add_account(email: str, password: str, chat_id: str) -> None:
    with _conn() as conn:
        conn.execute('INSERT INTO accounts(email, password_enc, chat_id, created_at) VALUES (?,?,?,?)',(email.strip().lower(), encrypt(password), (chat_id or '').strip(), datetime.now().isoformat(timespec='seconds')))

def upsert_account(email: str, password: str, chat_id: str) -> str:
    email = email.strip().lower()
    chat_id = str(chat_id or '').strip()
    with _conn() as conn:
        row = conn.execute('SELECT id, chat_id FROM accounts WHERE email = ?', (email,)).fetchone()
        if row:
            owner = (row['chat_id'] or '').strip()
            if owner and owner != chat_id:
                raise PermissionError('owned_by_other')
            conn.execute('UPDATE accounts SET password_enc = ?, chat_id = ? WHERE id = ?',(encrypt(password), chat_id, row['id']))
            return 'updated'
        conn.execute('INSERT INTO accounts(email, password_enc, chat_id, created_at) VALUES (?,?,?,?)',(email, encrypt(password), chat_id, datetime.now().isoformat(timespec='seconds')))
        return 'added'

def delete_account_by_email(email: str, chat_id: str | None = None) -> bool:
    email = email.strip().lower()
    with _conn() as conn:
        if chat_id is None:
            row = conn.execute('SELECT id FROM accounts WHERE email = ?', (email,)).fetchone()
        else:
            row = conn.execute('SELECT id FROM accounts WHERE email = ? AND chat_id = ?',(email, str(chat_id).strip())).fetchone()
        if not row:
            return False
        conn.execute('DELETE FROM claim_log WHERE account_id = ?', (row['id'],))
        conn.execute('DELETE FROM accounts WHERE id = ?', (row['id'],))
    return True

def get_accounts(chat_id: str | None = None) -> list[dict]:
    with _conn() as conn:
        if chat_id is None:
            rows = conn.execute('SELECT id, email, password_enc, chat_id FROM accounts ORDER BY id').fetchall()
        else:
            rows = conn.execute('SELECT id, email, password_enc, chat_id FROM accounts WHERE chat_id = ? ORDER BY id',(str(chat_id),)).fetchall()
    return [{'id': r['id'], 'email': r['email'], 'password': decrypt(r['password_enc']), 'chat_id': r['chat_id'] or ''} for r in rows]

def delete_account(account_id: int) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM claim_log WHERE account_id = ?', (account_id,))
        conn.execute('DELETE FROM accounts WHERE id = ?', (account_id,))

def log_claim(account_id: int, reward: str | None, tokens: str | None,screenshot: str | None, status: str) -> None:
    with _conn() as conn:
        conn.execute('INSERT INTO claim_log(account_id, claimed_at, reward, tokens, screenshot, status) ''VALUES (?,?,?,?,?,?)',(account_id, datetime.now().isoformat(timespec='seconds'),reward, tokens, screenshot, status))
