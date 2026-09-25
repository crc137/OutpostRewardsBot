import os
import re
from datetime import datetime
from playwright.sync_api import sync_playwright
EVENT_URL = 'https://outpost.dyinglightgame.com/events/dltb-1anniversary'
SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screenshots')
HEADLESS = True
SEL_SIGNIN_OPEN = '.page-nav__user-avatar.signinPop'
SEL_POPUP = '.popSignin'
SEL_EMAIL = '#fMailSignin'
SEL_PASSWORD = '#fPwdSignin'
SEL_SUBMIT = 'form.signupTmplLog button[type="submit"]'
SEL_LOGGED_NICK = '.onlogUsername'
SEL_TOKENS = '#tokensMiniInfo'
SEL_CLAIM = '.rewardClaim'
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
def _safe_email(email):
    return re.sub(r'[^a-zA-Z0-9_.-]', '_', email)
def _accept_cookies(page, progress=print):
    for name in ('Allow all', 'Accept all', 'Разрешить все', 'Принять все'):
        btn = page.get_by_role('button', name=re.compile(re.escape(name), re.I))
        try:
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(600)
                progress('Cookie banner closed')
                return
        except Exception:
            pass
def _read_login_error(page):
    for sel in ('.popSignin .error', '.popSignin .formError', '.notif',
                '#notif', '.notification', '.toast', '.alert'):
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                txt = loc.first.inner_text().strip()
                if txt:
                    return txt
        except Exception:
            pass
    return ''
def _login(page, email, password, progress=print):
    try:
        nick = page.locator(SEL_LOGGED_NICK).first.inner_text().strip()
        if nick:
            return nick
    except Exception:
        pass
    page.locator(SEL_SIGNIN_OPEN).first.click(timeout=15000)
    page.locator(SEL_POPUP).wait_for(state='visible', timeout=15000)
    page.wait_for_timeout(500)
    page.locator(SEL_EMAIL).fill(email, timeout=15000)
    page.locator(SEL_PASSWORD).fill(password, timeout=15000)
    page.locator(SEL_SUBMIT).first.click(timeout=15000)
    try:
        page.wait_for_selector(SEL_LOGGED_NICK + ':not(:empty)', timeout=30000)
    except Exception:
        err = _read_login_error(page)
        hint = ' Site error: ' + err if err else ''
        raise RuntimeError('Login failed after 30s.' + hint + ' Check email/password and ERROR_*.png')
    return page.locator(SEL_LOGGED_NICK).first.inner_text().strip()
def _dismiss_error_popup(page, progress=print):
    popup = page.locator('.popUp.popModern.err.open')
    txt = ''
    try:
        if popup.count() == 0:
            return ''
        txt = popup.first.inner_text().strip()
        if txt:
            progress('Site popup: ' + txt[:200])
    except Exception:
        pass
    try:
        close = popup.first.locator('.close')
        if close.count() > 0:
            close.first.click(timeout=2000)
            page.wait_for_timeout(500)
            return txt
    except Exception:
        pass
    try:
        page.keyboard.press('Escape')
        page.wait_for_timeout(400)
    except Exception:
        pass
    try:
        page.evaluate("() => { document.querySelectorAll('.popUp.popModern.err.open').forEach(e => e.classList.remove('open')); }")
        page.wait_for_timeout(300)
    except Exception:
        pass
    return txt
def _claim_rewards(page, email, ts, progress=print):
    rewards = []
    shots = []
    fail_shots = []
    hints = []
    failed = set()
    def _record_fail(tile, day, month, name, txt):
        if not txt:
            txt = 'claim failed'
        hints.append(day + ' ' + month + ' ' + name + ': ' + txt)
        try:
            if tile.count() > 0:
                p = os.path.join(SCREENSHOT_DIR, _safe_email(email) + '_' + ts + '_fail' + str(len(fail_shots)) + '.png')
                if _shoot_tile(page, tile, p):
                    fail_shots.append(p)
                    progress('Fail screenshot saved: ' + p)
                else:
                    progress('Fail screenshot skipped (no box)')
            else:
                progress('Fail screenshot skipped (no tile)')
        except Exception as ex:
            progress('Fail screenshot error: ' + str(ex)[:200])
    for _ in range(25):
        _dismiss_error_popup(page, progress)
        btns = page.locator(SEL_CLAIM + ':visible')
        if btns.count() == 0:
            break
        btn = None
        rid = ''
        for i in range(btns.count()):
            b = btns.nth(i)
            try:
                r = b.get_attribute('data-reward-id') or str(i)
            except Exception:
                r = str(i)
            if r not in failed:
                btn = b
                rid = r
                break
        if btn is None:
            break
        tile = btn.locator('xpath=ancestor::div[contains(@class,"tile")][1]')
        name = 'Daily reward'
        day = ''
        month = ''
        try:
            if tile.count() > 0:
                nm = tile.locator('.name').first.inner_text().strip()
                if nm:
                    name = nm
                day = tile.locator('.date .day').first.inner_text().strip()
                month = tile.locator('.date .month').first.inner_text().strip()
        except Exception:
            pass
        try:
            btn.click(timeout=5000)
        except Exception as e:
            txt = _dismiss_error_popup(page, progress)
            if 'platform linked' in txt:
                return rewards, shots, fail_shots, hints, txt
            progress('Claim click failed: ' + str(e)[:200])
            _record_fail(tile, day, month, name, txt)
            failed.add(rid)
            continue
        page.wait_for_timeout(2500)
        txt = _dismiss_error_popup(page, progress)
        if 'platform linked' in txt:
            return rewards, shots, fail_shots, hints, txt
        ok = False
        try:
            tiles = page.locator('.tile:has(.rw.claimed)')
            for j in range(tiles.count()):
                t = tiles.nth(j)
                try:
                    d = t.locator('.date .day').first.inner_text().strip()
                    m = t.locator('.date .month').first.inner_text().strip()
                    n = t.locator('.name').first.inner_text().strip()
                except Exception:
                    continue
                if d == day and m == month and n == name:
                    ok = True
                    p = os.path.join(SCREENSHOT_DIR, _safe_email(email) + '_' + ts + '_' + str(len(shots)) + '.png')
                    if _shoot_tile(page, t, p):
                        shots.append(p)
                    break
        except Exception:
            pass
        if not ok:
            progress('Claim failed: ' + name)
            _record_fail(tile, day, month, name, txt)
            failed.add(rid)
            continue
        rewards.append(name)
        progress('Claimed: ' + name)
    return rewards, shots, fail_shots, hints, ''
def _shoot_tile(page, tile, shot):
    tile.scroll_into_view_if_needed()
    page.wait_for_timeout(1200)
    box = tile.bounding_box()
    if not box:
        return False
    sx = page.evaluate('() => window.scrollX')
    sy = page.evaluate('() => window.scrollY')
    clip = {
        'x': max(0, box['x'] + sx - 6),
        'y': max(0, box['y'] + sy - 6),
        'width': box['width'] + 12,
        'height': box['height'] + 12,
    }
    page.screenshot(path=shot, clip=clip, full_page=True)
    return True
def process_account(playwright, account, progress=print):
    email = account['email']
    res = {'ok': False, 'email': email, 'reward': None, 'tokens': None,
           'screenshot': None, 'error': None}
    browser = playwright.chromium.launch(
        headless=HEADLESS,
        args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
    )
    context = browser.new_context(
        viewport={'width': 1366, 'height': 900},
        locale='ru-RU',
        user_agent=('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'),
    )
    page = context.new_page()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        progress('[' + email + '] Opening event page...')
        page.goto(EVENT_URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(2000)
        _accept_cookies(page, progress)
        nick = _login(page, email, account['password'], progress)
        progress('[' + email + '] Logged in as ' + nick)
        page.wait_for_timeout(1500)
        tokens_before = page.locator(SEL_TOKENS).first.inner_text().strip()
        rewards, claim_shots, fail_shots, hints, claim_err = _claim_rewards(page, email, ts, progress)
        if 'platform linked' in claim_err:
            res['remove'] = True
            raise RuntimeError('This account has no linked game platform. Account removed from the bot.')
        if rewards:
            res['reward'] = '; '.join(rewards)
            res['screenshots'] = claim_shots
            try:
                page.reload(wait_until='domcontentloaded', timeout=60000)
                page.wait_for_timeout(2000)
            except Exception:
                pass
        elif hints:
            res['reward'] = 'Nothing claimed today.'
            res['screenshots'] = fail_shots
        else:
            res['reward'] = 'No rewards available today'
            res['screenshots'] = []
        if hints:
            clean = []
            for h in hints:
                if 'play the game' in h.lower():
                    clean.append(h.split(':')[0] + ': launch the game to unlock this reward')
                else:
                    clean.append(h)
            res['reward'] += '\nNot claimed: ' + ' | '.join(clean)
        res['reward'] = res['reward'][:900]
        tokens_after = page.locator(SEL_TOKENS).first.inner_text().strip()
        res['tokens'] = tokens_before + ' -> ' + tokens_after
        if res['screenshots']:
            res['screenshot'] = res['screenshots'][-1]
        res['ok'] = True
        progress('[' + email + '] Done: ' + res['reward'].split('\n')[0][:100])
    except Exception as e:
        res['error'] = str(e)[:500]
        progress('[' + email + '] ERROR: ' + res['error'])
        try:
            err_shot = os.path.join(SCREENSHOT_DIR, 'ERROR_' + _safe_email(email) + '_' + ts + '.png')
            page.screenshot(path=err_shot, full_page=True)
            res['screenshot'] = err_shot
        except Exception:
            pass
    finally:
        context.close()
        browser.close()
    return res
def run_collection(accounts, progress=print, on_account=None):
    results = []
    with sync_playwright() as p:
        for acc in accounts:
            r = process_account(p, acc, progress=progress)
            results.append(r)
            if on_account:
                on_account(r)
            progress('-' * 60)
    return results
