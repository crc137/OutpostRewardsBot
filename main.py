import argparse
import os
import sqlite3
import sys
import queue
import threading

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database
from bot import run_collection
from notifier import send_report

DONE_MARK = '__DONE__'

def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ModuleNotFoundError as e:
        print(f'Tkinter is not available in this environment ({e}). Default is the Telegram bot.',file=sys.stderr)
        sys.exit(1)

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title('DL Outpost — Daily Reward Collection')
            self.geometry('860x580')
            database.init_db()
            self.log_queue: queue.Queue = queue.Queue()
            self._build_ui()
            self.refresh_accounts()
            self.after(100, self._poll_log)

        def _build_ui(self):
            top = ttk.Frame(self)
            top.pack(fill='x', padx=8, pady=8)
            ttk.Button(top, text='Add Account', command=self.add_account_dialog).pack(side='left')
            ttk.Button(top, text='Delete Selected', command=self.delete_selected).pack(side='left', padx=(6, 0))
            self.run_btn = ttk.Button(top, text='Start Collection', command=self.start_collection)
            self.run_btn.pack(side='right')
            cols = ('id', 'email', 'chat_id', 'added')
            self.tree = ttk.Treeview(self, columns=cols, show='headings', height=10, selectmode='browse')
            self.tree.heading('id', text='ID')
            self.tree.heading('email', text='Email')
            self.tree.heading('chat_id', text='Telegram Chat ID')
            self.tree.heading('added', text='Added')
            self.tree.column('id', width=40, anchor='center')
            self.tree.column('email', width=300)
            self.tree.column('chat_id', width=180)
            self.tree.column('added', width=140)
            self.tree.pack(fill='x', padx=8)
            self.log = tk.Text(self, height=14, state='disabled', wrap='word', bg='#1e1e1e', fg='#d4d4d4', insertbackground='white')
            self.log.pack(fill='both', expand=True, padx=8, pady=(8, 8))

        def _log(self, msg: str):
            self.log.configure(state='normal')
            self.log.insert('end', msg + '\n')
            self.log.see('end')
            self.log.configure(state='disabled')

        def refresh_accounts(self):
            self.tree.delete(*self.tree.get_children())
            with database._conn() as conn:
                rows = conn.execute('SELECT id, email, chat_id, created_at FROM accounts ORDER BY id').fetchall()
            for r in rows:
                self.tree.insert('','end',iid=str(r['id']),values=(r['id'], r['email'], r['chat_id'] if r['chat_id'] else '—', r['created_at']))

        def add_account_dialog(self):
            dlg = tk.Toplevel(self)
            dlg.title('Add Account')
            dlg.transient(self)
            dlg.grab_set()
            dlg.resizable(False, False)

            ttk.Label(dlg, text='Account Email:').grid(row=0, column=0, sticky='w', padx=12, pady=(12, 2))
            email_e = ttk.Entry(dlg, width=38)
            email_e.grid(row=1, column=0, padx=12)
            email_e.focus_set()

            ttk.Label(dlg, text='Password:').grid(row=2, column=0, sticky='w', padx=12, pady=(8, 2))
            pwd_e = ttk.Entry(dlg, width=38, show='•')
            pwd_e.grid(row=3, column=0, padx=12)

            ttk.Label(dlg, text='Telegram Chat ID (to whom reports will be sent):').grid(row=4, column=0, sticky='w', padx=12, pady=(8, 2))
            chat_e = ttk.Entry(dlg, width=38)
            chat_e.grid(row=5, column=0, padx=12)

            status = ttk.Label(dlg,text='The password will be encrypted. A report will be sent via Telegram to this chat ID.',foreground='#888',wraplength=300,justify='left')
            status.grid(row=6, column=0, padx=12, pady=(4, 0), sticky='w')

            def save():
                email = email_e.get().strip()
                pwd = pwd_e.get()
                chat_id = chat_e.get().strip()
                if not email or '@' not in email:
                    status.configure(text='Please enter a valid email address.', foreground='red')
                    return
                if not pwd:
                    status.configure(text='Please enter a password.', foreground='red')
                    return
                if not chat_id:
                    status.configure(text='Please enter a chat ID.', foreground='red')
                    return
                try:
                    database.add_account(email, pwd, chat_id)
                except sqlite3.IntegrityError:
                    status.configure(text='This account already exists.', foreground='red')
                    return
                dlg.destroy()
                self.refresh_accounts()
                self._log(f'Account added: {email} → reports for chat {chat_id}')

            pwd_e.bind('<Return>', lambda e: save())
            chat_e.bind('<Return>', lambda e: save())
            ttk.Button(dlg, text='Save', command=save).grid(row=7, column=0, pady=14)

        def delete_selected(self):
            sel = self.tree.selection()
            if not sel:
                return
            acc_id = int(sel[0])
            email = self.tree.item(sel[0], 'values')[1]
            if messagebox.askyesno('Delete', f'Delete account {email}?'):
                database.delete_account(acc_id)
                self.refresh_accounts()
                self._log(f'Account deleted: {email}')

        def start_collection(self):
            accounts = database.get_accounts()
            if not accounts:
                messagebox.showinfo('No Accounts', 'Please add at least one account first.')
                return
            self.run_btn.configure(state='disabled')
            self._log(f'Starting collection for {len(accounts)} account(s)…')
            threading.Thread(target=self._worker, args=(accounts,), daemon=True).start()

        def _worker(self, accounts):
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

            run_collection(accounts, progress=self.log_queue.put, on_account=on_account)
            self.log_queue.put(DONE_MARK)

        def _poll_log(self):
            try:
                while True:
                    msg = self.log_queue.get_nowait()
                    if msg == DONE_MARK:
                        self.run_btn.configure(state='normal')
                        self._log('Collection finished.')
                    else:
                        self._log(str(msg))
            except queue.Empty:
                pass
            self.after(100, self._poll_log)

    App().mainloop()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='DL Outpost daily reward collector')
    parser.add_argument('--gui', action='store_true', help='Open Tkinter UI (needs _tkinter)')
    parser.add_argument('--run-once', action='store_true', help='Claim all stored accounts once, then exit')
    args = parser.parse_args()

    if args.gui:
        run_gui()
    elif args.run_once:
        from telegram_bot import run_claims

        database.init_db()
        accs = database.get_accounts()
        if not accs:
            print('No accounts yet. Users add them in Telegram with /add.')
            sys.exit(0)
        run_claims(accs, progress=print)
        print('Collection finished.')
    else:
        from telegram_bot import run_bot

        run_bot()
