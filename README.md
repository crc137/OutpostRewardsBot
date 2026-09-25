# DL Outpost Rewards Bot

Telegram bot that auto-collects Dying Light Outpost daily rewards for accounts
that users add themselves. Open source: https://github.com/crc137/OutpostRewardsBot

Each user adds their own accounts in the bot (or in the built-in Mini App) and
gets personal reports with reward card screenshots. Passwords are stored
encrypted (Fernet).

## Requirements

- Python 3.10+
- A Telegram bot token from @BotFather
- (for hosting) a server with a public HTTPS URL for the Mini App

## Run locally

    git clone https://github.com/crc137/OutpostRewardsBot.git
    cd OutpostRewardsBot
    pip install -r requirements.txt
    playwright install chromium

Create `.env` in the project folder:

    TG_BOT_TOKEN=123456:abc-your-token-from-botfather

Run:

    python main.py

Open the bot in Telegram, press /start, add an account with the menu and press
Claim. Locally the Mini App is off (it needs a public PORT); everything else
works.

Useful flags:

    python main.py --run-once   # collect once for all accounts and exit
    python main.py --gui        # desktop window (needs tkinter)

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| TG_BOT_TOKEN | yes | BotFather token |
| PORT | hosting only | Port for the Mini App + healthcheck |
| APP_URL | no | Public https URL, enables the "Open app" menu button |
| CLAIM_INTERVAL_HOURS | no | Scheduler interval, default 24 |
| FERNET_KEY | no | Encryption key; otherwise secret.key file is created |

## Deploy (hosting with HTTPS, e.g. Railway/Render)

1. Push the repo to GitHub and deploy it on your host.
2. Set env vars: TG_BOT_TOKEN and PORT (hosts provide it automatically).
3. After deploy set APP_URL=https://your-host/ and restart.
4. In @BotFather:
   - /newapp -> choose your bot -> URL https://your-host/
     The link t.me/<bot>/<app> opens the Mini App.
   - Bot Settings -> Menu Button -> same URL (optional).
   - Remove the command list (/setcommands) - the bot uses buttons.
5. Data (accounts.db, secret.key) lives on the host disk. On a fresh deploy
   the database is empty - users re-add their accounts.

## Project structure

    main.py            entry point: bot (default), --gui, --run-once
    telegram_bot.py    Telegram bot: inline menu, add flow, scheduler
    webapp.py          Mini App server: JSON API + serves index.html
    index.html         Mini App front-end (Accounts / Calendar tabs)
    bot.py             Playwright: login, claim, card screenshots
    database.py        SQLite: accounts (encrypted passwords) + claim log
    crypto_utils.py    Fernet encryption
    notifier.py        Telegram reports: photos + rich tables

## Security

- Never share accounts.db and secret.key together - they give the passwords.
- The Mini App API validates Telegram initData (HMAC with the bot token),
  it cannot be used outside Telegram.
- Automation may violate Techland rules. Use at your own risk; accounts can
  be banned.
