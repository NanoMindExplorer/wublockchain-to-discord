#!/usr/bin/env python3
"""Wu Blockchain mirror: Telegram channel -> Discord (Bahasa Indonesia).

Polls the public preview page https://t.me/s/<channel> and relays every NEW
post to Discord as it appears (poll every POLL_SECONDS inside a long-lived
job; cron restarts the job every 5 h for a 24/7 mirror).

The source posts are in English; each post is AUTO-TRANSLATED to Indonesian
(TARGET_LANG, default "id") before it is sent to Discord, so the Discord
channel receives the news in Bahasa Indonesia.

Translation (accuracy-first, no paid key required by default):
  - DeepL free API when DEEPL_API_KEY is set (best accuracy).
  - Otherwise Google Translate (keyless endpoint), chunked per paragraph,
    then a crypto glossary pass that restores terms machine translation
    commonly mangles (tickers, proper nouns, crypto jargon) and keeps
    numbers / dates / URLs untouched. If translation fails, the original
    text is sent so the news still arrives.

State lives in state.json (last relayed message id). A post is marked
relayed only after Discord accepted the message (HTTP 200/204) — failed
delivery stays pending and is retried next poll.

Pages show ~20 latest posts; message ids monotonically increase, so the
cursor survives downtime as long as fewer than ~20 posts arrive while the
job is restarting.

Env: DC_WEBHOOK (Discord webhook in the target channel), optional
CHANNEL (default wublockchainenglish), POLL_SECONDS, TARGET_LANG
(default id), DEEPL_API_KEY (optional).
"""
import json, os, re, subprocess, sys, time, urllib.request, urllib.error, urllib.parse
import html as HTML

CHANNEL = os.environ.get("CHANNEL", "").strip() or "wublockchainenglish"
WEBHOOK = os.environ.get("DC_WEBHOOK", "")
DEEPL_KEY = os.environ.get("DEEPL_API_KEY", "").strip()
TARGET_LANG = os.environ.get("TARGET_LANG", "").strip() or "id"
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "state.json")
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "30"))
UA = "Mozilla/5.0 (X11; Linux x86_64) wublockchain-to-discord/1.0"

POSTED = 0
FAILED = 0


def fetch_html():
    req = urllib.request.Request(f"https://t.me/s/{CHANNEL}",
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}")
        return r.read().decode("utf-8", "replace")


def parse_posts(html):
    """Return sorted list of (id, body, iso_time)."""
    blocks = re.findall(
        r'data-post="' + CHANNEL + r'/(\d+)"(.*?)(?=<div class="tgme_widget_message[ "]|</section>)',
        html, re.S)
    out = []
    for pid, seg in blocks:
        m = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>\s*'
            r'(?:<a class="tgme_widget_message_reply|<div class="tgme_widget_message_footer|<time|<span)',
            seg, re.S)
        body = m.group(1) if m else ""
        media = "<div class=\"tgme_widget_message_photo" in seg \
            or "tgme_widget_message_video" in seg
        # links: keep visible text but append the href when it's not the
        # usual generic text-preview
        body = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                      lambda x: x.group(2), body)
        body = re.sub(r'<br/?>?', '\n', body)
        body = re.sub(r'<[^>]+>', '', body)
        body = HTML.unescape(body).strip()
        if not body and media:
            body = "(media only)"
        t = re.search(r'<time datetime="([^"]+)"', seg)
        if body:
            out.append((int(pid), body, t and t.group(1) or ""))
    return sorted(set(out))


def load_state():
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {}


# ---------------------------------------------------------------- translation
# Post-translation glossary: fixes terms Google Translate commonly mangles
# in crypto news, restoring the form the Indonesian crypto community uses.
# Applied as whole-word, case-insensitive replacements on the translated
# text. (Tickers, proper nouns, numbers and URLs are already preserved by
# the translator; this list only covers the known weak spots.)
GLOSSARY = [
    (r"\bpenurunan udara\b", "airdrop"),
    (r"\bpenurunan\b", "airdrop"),          # bare "airdrop" mistranslated
    (r"\bpaus\b", "whale"),
    (r"\bpaus-paus\b", "whale"),
    (r"\btaruhan\b", "staking"),
    (r"\bmempertaruhkan\b", "staking"),
    (r"\bpembakaran\b", "burn"),
    (r"\bmembakar\b", "burn"),
    (r"\bpencetakan\b", "mint"),
    (r"\bmencetak\b", "mint"),
    (r"\bpenambangan\b", "mining"),
    (r"\bdompet\b", "wallet"),
    (r"\bbanteng\b", "bullish"),
    (r"\bberuang\b", "bearish"),
    (r"\bpompa\b", "pump"),
    (r"\btempat pembuangan\b", "dump"),
    (r"\bketakutan, ketidakpastian, dan keraguan\b", "FUD"),
    (r"\bpertukaran terdesentralisasi\b", "DEX"),
    (r"\bpertukaran terpusat\b", "CEX"),
    (r"\borganisasi otonom terdesentralisasi\b", "DAO"),
    (r"\btoken yang tidak dapat dipertukarkan\b", "NFT"),
    (r"\bkeuangan terdesentralisasi\b", "DeFi"),
]


def apply_glossary(text):
    for pat, rep in GLOSSARY:
        text = re.sub(pat, rep, text, flags=re.I)
    return text


def _google_translate_chunk(text, target):
    data = urllib.parse.urlencode({
        "client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text,
    }).encode()
    req = urllib.request.Request(
        "https://translate.googleapis.com/translate_a/single",
        data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    parts = []
    for seg in payload[0] or []:
        if seg and seg[0]:
            parts.append(seg[0])
    return "".join(parts)


def translate_google(text, target):
    """Keyless Google Translate, chunked per paragraph (<=1500 chars)."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 1500 and cur:
            chunks.append(cur)
            cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        out.append(_google_translate_chunk(c, target))
    return "\n".join(out)


def translate_deepl(text, target):
    data = urllib.parse.urlencode({
        "auth_key": DEEPL_KEY, "text": text,
        "target_lang": target.upper(),
    }).encode()
    req = urllib.request.Request("https://api-free.deepl.com/v2/translate",
                                 data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    return payload["translations"][0]["text"]


def translate_to_id(text):
    """English/any -> TARGET_LANG. Falls back to the original on failure."""
    if not text or TARGET_LANG.lower() in ("en", "eng"):
        return text
    try:
        if DEEPL_KEY:
            try:
                return apply_glossary(translate_deepl(text, TARGET_LANG))
            except Exception as e:
                print(f"deepl failed ({e}), falling back to google", file=sys.stderr)
        return apply_glossary(translate_google(text, TARGET_LANG))
    except Exception as e:
        print(f"translation failed ({e}); sending original text", file=sys.stderr)
        return text


# ---------------------------------------------------------------- delivery
def deliver(body_text, pid):
    """True only when Discord accepted (HTTP 200/204). Retries 429/5xx."""
    global POSTED, FAILED
    body = json.dumps({
        "username": os.environ.get("BOT_NAME", "Kabar Burung"),
        "content": body_text[:2000],
        "allowed_mentions": {"parse": []},
    }).encode()
    for attempt in range(3):
        req = urllib.request.Request(WEBHOOK, data=body,
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status in (200, 204):
                    POSTED += 1
                    return True
                raise RuntimeError(f"HTTP {r.status}")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 + attempt * 3)
                continue
            print(f"delivery failed (id {pid}): HTTP {e.code}", file=sys.stderr)
        except Exception as e:
            print(f"delivery failed (id {pid}): {e}", file=sys.stderr)
        break
    FAILED += 1
    return False


def run_cycle(state):
    html = fetch_html()
    posts = parse_posts(html)
    last = state.get("last_post") or 0
    fresh = [p for p in posts if p[0] > (last or 0)]
    if fresh and not last:
        # first EVER read: baseline only (no flood)
        state["last_post"] = max(p[0] for p in posts)
        return state, True   # baseline → tell the caller to save+banner
    if fresh:
        for pid, body, iso in sorted(fresh):
            # terjemahkan ke Bahasa Indonesia dulu, baru kirim ke Discord
            text_id = translate_to_id(body)
            stamp = f"\n\n[Sumber: Wu Blockchain · Telegram — {iso[:16].replace('T', ' ')} UTC]({f'https://t.me/{CHANNEL}/{pid}'})"
            if deliver(text_id + stamp, pid):
                state["last_post"] = pid
                # kecilkan gap antar post (limit webhook Discord ~5/3s)
                time.sleep(1)
            else:
                break   # jangan lonjakan cursor: biarkan retry di siklus berikutnya
    return state, False


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, sort_keys=True, indent=1)
    os.replace(tmp, STATE_PATH)


def commit_state():
    r = subprocess.run(["git", "status", "--porcelain", "--", "state.json"],
                       cwd=HERE, capture_output=True, text=True)
    if not r.stdout.strip():
        return False
    try:
        subprocess.run(["git", "add", "state.json"], cwd=HERE, check=True)
        subprocess.run(["git", "commit", "-m", "mirror state [skip ci]"],
                       cwd=HERE, check=True)
        head = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                              cwd=HERE, capture_output=True, text=True).stdout.strip()
        ok = subprocess.run(["git", "push", "origin", head], cwd=HERE,
                            capture_output=True, text=True)
        if ok.returncode != 0:
            subprocess.run(["git", "pull", "--rebase", "origin", head], cwd=HERE,
                           capture_output=True)
            subprocess.run(["git", "push", "origin", head], cwd=HERE,
                           capture_output=True)
    except Exception as e:
        print(f"commit_state: {e}", file=sys.stderr)
    return True


def main():
    if not WEBHOOK:
        print("DC_WEBHOOK not set", file=sys.stderr)
        return 2
    banner = {"username": os.environ.get("BOT_NAME", "Kabar Burung"),
              "content": f"🟢 Mirror t.me/{CHANNEL} terhubung — berita Wu Blockchain masuk ke sini dalam Bahasa Indonesia (sumber: https://t.me/s/{CHANNEL})"}
    state = load_state()
    lifetime = None
    if "--loop" in sys.argv:
        i = sys.argv.index("--loop")
        lifetime = (float(sys.argv[i + 1]) if len(sys.argv) > i + 1
                    and sys.argv[i + 1].replace(".", "", 1).isdigit() else 330.0) * 60
    deadline = time.time() + (lifetime or 30)   # once = snapshot singkat lalu exit
    first = not state.get("initialized")
    banner_sent = False
    cycle = 0
    backoff = 5
    while time.time() < deadline:
        cycle += 1
        try:
            state, baseline = run_cycle(state)
            changed = baseline or state.get("last_post") != (load_state().get("last_post"))
            if changed:
                save_state(state)
                commit_state()
            if first and not banner_sent:
                if deliver(banner["content"], 0):
                    banner_sent = True
                    state["initialized"] = True
                    save_state(state)
                    commit_state()
                    first = False
            backoff = 5
        except Exception as e:
            print(f"cycle {cycle} error: {e} — retrying in {backoff}s", file=sys.stderr)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
            continue
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(POLL_SECONDS, remaining))
    print(f"done: {POSTED} posted, {FAILED} failed, {cycle} cycles")
    return 1 if FAILED and not POSTED else 0


if __name__ == "__main__":
    sys.exit(main())
