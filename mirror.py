#!/usr/bin/env python3
"""Public Telegram channel -> Discord webhook mirror (no bot admin needed).

Polls the public preview page https://t.me/s/<channel> and relays every NEW
post to Discord as it appears (poll every POLL_SECONDS inside a long-lived
job; cron restarts the job every 5 h for a 24/7 mirror).

State lives in state.json (last relayed message id). A post is marked
relayed only after Discord accepted the message (HTTP 200/204) — failed
delivery stays pending and is retried next poll.

Pages show ~20 latest posts; message ids monotonically increase, so the
cursor survives downtime as long as fewer than ~20 posts arrive while the
job is restarting.

Env: DC_WEBHOOK (Discord webhook in the target channel), optional
CHANNEL (default wublockchainenglish), POLL_SECONDS.
"""
import json, os, re, subprocess, sys, time, urllib.request, urllib.error
import html as HTML

CHANNEL = os.environ.get("CHANNEL", "").strip() or "wublockchainenglish"
WEBHOOK = os.environ.get("DC_WEBHOOK", "")
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
            stamp = f"\n\n[Wu Blockchain · Telegram — {iso[:16].replace('T', ' ')} UTC]({f'https://t.me/{CHANNEL}/{pid}'})"
            if deliver(body + stamp, pid):
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
              "content": f"🟢 Mirror t.me/{CHANNEL} terhubung — berita baru masuk ke sini (source: https://t.me/s/{CHANNEL})"}
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
