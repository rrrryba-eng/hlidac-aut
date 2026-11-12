#!/usr/bin/env python3
"""Hlídač nových inzerátů aut.

Projde uložená hledání z config.yaml (Sauto, TipCars, Bazoš, AutoScout24, mobile.de…),
porovná inzeráty s těmi, které už viděl (seen.json), a nové pošle e-mailem a SMS.

Spuštění:
  python hlidac.py          # normální běh (hlídání + upozornění)
  python hlidac.py --test   # jen vypíše, co na stránkách našel, nic neposílá ani neukládá
"""
import datetime as dt
import json
import os
import re
import smtplib
import sys
import unicodedata
from email.mime.text import MIMEText
from urllib.parse import parse_qs, urlparse, urlunparse

import requests
import yaml
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(ROOT, "seen.json")
CONFIG_FILE = os.path.join(ROOT, "config.yaml")
FORGET_AFTER_DAYS = 30  # inzerát, který nebyl vidět 30 dní, se zapomene

# Podle čeho se na stránce poznají odkazy na detail inzerátu (lze přepsat v config.yaml klíčem "vzor")
DEFAULT_PATTERNS = {
    "sauto.cz": r"/detail/",
    "tipcars.com": r"-\d{5,}\.html",
    "bazos.cz": r"/inzerat/\d+",
    "bazos.sk": r"/inzerat/\d+",
    "autoscout24": r"/(angebote|offers|nabidky|ponuky)/",
    "mobile.de": r"details\.html\?id=\d+",
}

CONSENT_BUTTONS = [
    "Souhlasím", "Přijmout vše", "Přijmout", "Rozumím", "Povolit vše",
    "Súhlasím", "Prijať všetko",
    "Alle akzeptieren", "Akzeptieren", "Einverstanden",
    "Accept all", "Accept",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

LINKS_JS = """
els => els.map(e => {
  let t = (e.innerText || '').trim();
  if (t.length < 25) {
    const c = e.closest('article, li, [class*="item"], [class*="card"], [class*="result"]');
    if (c && c.innerText) t = c.innerText;
  }
  return [e.href, t];
})
"""


# ---------- stav ----------

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)


# ---------- stahování ----------

def default_pattern(url):
    host = urlparse(url).netloc
    for key, pattern in DEFAULT_PATTERNS.items():
        if key in host:
            return pattern
    return r"\d{6,}"


def normalize(href):
    """Jednotný klíč inzerátu (bez parametrů z URL, aby se stejný kus nehlásil dvakrát)."""
    p = urlparse(href)
    if "mobile.de" in p.netloc:
        return "mobile.de:" + parse_qs(p.query).get("id", [""])[0]
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", "", ""))


def accept_cookies(page):
    for name in CONSENT_BUTTONS:
        try:
            page.get_by_role("button", name=name).first.click(timeout=1200)
            return True
        except Exception:
            continue
    return False


def fetch_listings(page, url, pattern):
    rx = re.compile(pattern)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    if accept_cookies(page):
        page.wait_for_timeout(2000)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    for _ in range(6):  # doscrollovat, aby se načetly všechny výsledky
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(700)

    host = urlparse(url).netloc.split(":")[0]
    base = ".".join(host.split(".")[-2:])
    found = {}
    for href, text in page.eval_on_selector_all("a[href]", LINKS_JS):
        if base not in urlparse(href).netloc or not rx.search(href):
            continue
        key = normalize(href)
        text = " ".join((text or "").split())[:200]
        if key not in found or len(text) > len(found[key][1]):
            found[key] = (href, text)
    return found


# ---------- upozornění ----------

def send_email(subject, body):
    host, to = os.getenv("SMTP_HOST"), os.getenv("EMAIL_TO")
    user, password = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not (host and to and user and password):
        print("E-mail není nastaven, přeskakuji.")
        return
    port = int(os.getenv("SMTP_PORT", "465"))
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls()
    with server:
        server.login(user, password)
        server.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    print("E-mail odeslán.")


def strip_diacritics(text):
    # SMS bez diakritiky = víc znaků na jednu zprávu = levnější
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def send_sms(text):
    sid, token = os.getenv("TWILIO_SID"), os.getenv("TWILIO_TOKEN")
    sender, to = os.getenv("TWILIO_FROM"), os.getenv("SMS_TO")
    if not (sid and token and sender and to):
        print("SMS není nastavena, přeskakuji.")
        return
    for number in to.split(","):
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, token),
            data={"From": sender, "To": number.strip(), "Body": strip_diacritics(text)},
            timeout=30,
        )
        if r.status_code >= 300:
            print("Chyba SMS:", r.status_code, r.text[:300])
        else:
            print("SMS odeslána na", number.strip())


def notify(new_items):
    lines = [f"[{name}]\n{text}\n{href}\n" for name, href, text in new_items]
    send_email(f"Nová auta: {len(new_items)} nových inzerátů", "\n".join(lines))
    max_sms = int(os.getenv("MAX_SMS", "5"))
    for name, href, text in new_items[:max_sms]:
        send_sms(f"Nove auto ({name}): {text[:70]} {href}")
    if len(new_items) > max_sms:
        send_sms(f"+ dalsich {len(new_items) - max_sms} novych inzeratu, viz e-mail.")


# ---------- hlavní běh ----------

def main():
    test = "--test" in sys.argv
    with open(CONFIG_FILE, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    searches = [s for s in cfg.get("hledani", []) if s.get("url", "").startswith("http")]
    if not searches:
        sys.exit("V config.yaml není žádné hledání s platným odkazem.")

    state = load_state()
    seen = state.setdefault("seen", {})
    initialized = set(state.setdefault("init", []))
    now = dt.datetime.now(dt.timezone.utc)
    now_s = now.isoformat(timespec="seconds")
    new_items, ok_count = [], 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="cs-CZ", user_agent=USER_AGENT,
                                  viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        for s in searches:
            name, url = s["nazev"], s["url"]
            try:
                found = fetch_listings(page, url, s.get("vzor") or default_pattern(url))
            except Exception as e:
                print(f"[{name}] CHYBA: {e}")
                continue
            ok_count += 1
            print(f"[{name}] nalezeno {len(found)} inzerátů")
            if test:
                for href, text in list(found.values())[:15]:
                    print("   -", text[:90], "|", href)
                continue
            first_run = name not in initialized
            for key, (href, text) in found.items():
                if key not in seen and not first_run:
                    new_items.append((name, href, text))
                seen[key] = now_s
            if first_run:
                print(f"[{name}] první běh: stávající inzeráty jen zapamatovány, bez upozornění")
            initialized.add(name)
        browser.close()

    if test:
        return

    cutoff = now - dt.timedelta(days=FORGET_AFTER_DAYS)
    state["seen"] = {k: v for k, v in seen.items() if dt.datetime.fromisoformat(v) >= cutoff}
    state["init"] = sorted(initialized)
    save_state(state)

    print(f"Nových inzerátů: {len(new_items)}")
    if new_items:
        notify(new_items)
    if ok_count == 0:
        sys.exit("Žádné hledání se nepodařilo načíst.")


if __name__ == "__main__":
    main()
