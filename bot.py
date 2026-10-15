# language: Python, file: bot.py
# sexalarab.net bot — 45s-300s, كاش, توكن من البيئة

import os, json, random, asyncio, re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
import yt_dlp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- CONFIG ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8232134538:AAFjjniY1Z_xILXJ14KbOT-Koc7WQ9Fl5XA")
OWNER_ID  = int(os.environ.get("OWNER_ID", "7485896377"))

BASE_URL    = "https://sexalarab.net/"
DOMAIN      = "https://sexalarab.net"
MIN_SEC     = 45
MAX_SEC     = 300
MAX_PAGES   = 5
OUT_DIR     = Path("downloads")
CACHE_FILE  = Path("cache.json")
TG_LIMIT_MB = 50
# ----------------------------

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Referer": "https://sexalarab.net/",
}


def fetch(url):
    return cffi_requests.get(
        url, headers=HEADERS, impersonate="chrome124",
        timeout=20, allow_redirects=True
    )


def is_video_url(url):
    if not url.startswith(DOMAIN):
        return False
    p = urlparse(url).path
    return p.startswith("/video/") and len(p) > 10


def parse_duration(text):
    m = re.match(r"(\d+):(\d+)", text.strip())
    if not m:
        return 0
    return int(m.group(1)) * 60 + int(m.group(2))


def collect_links_with_durations():
    results = {}
    queue, page = [BASE_URL], 0

    while queue and page < MAX_PAGES:
        url = queue.pop(0); page += 1
        try:
            r = fetch(url)
            print(f"[page {page}] {url} -> {r.status_code} ({len(r.text)}b)")
            if r.status_code != 200:
                continue
        except Exception as e:
            print(f"[skip] {type(e).__name__}: {e}")
            continue

        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            if not is_video_url(href):
                continue
            if href in results:
                continue

            text = a.get_text(" ", strip=True)
            dur = 0
            m = re.search(r"\b(\d{1,2}:\d{2})\b", text)
            if m:
                dur = parse_duration(m.group(1))
            if not dur:
                inner = a.find(string=re.compile(r"\b\d{1,2}:\d{2}\b"))
                if inner:
                    m2 = re.search(r"\b(\d{1,2}:\d{2})\b", str(inner))
                    if m2:
                        dur = parse_duration(m2.group(1))

            results[href] = dur

        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"])
            if re.search(r"/page/\d+", href) or "?page=" in href:
                if href.startswith(DOMAIN) and href not in queue:
                    queue.append(href)

    return results


def build_cache_sync():
    links = collect_links_with_durations()
    print(f"[+] {len(links)} روابط")
    cache = []
    for u, dur in links.items():
        if dur == 0:
            continue
        cache.append({"url": u, "dur": dur, "title": "", "size": 0})
        mark = "OK" if MIN_SEC <= dur <= MAX_SEC else "--"
        print(f"[{mark}] {dur:>4}s  {u[-60:]}")

    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    return cache


def load_cache():
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return []
    return []


def eligible(cache):
    return [c for c in cache if MIN_SEC <= c["dur"] <= MAX_SEC]


def download_one(url):
    OUT_DIR.mkdir(exist_ok=True)
    opts = {
        "outtmpl": str(OUT_DIR / "%(id)s.%(ext)s"),
        "format": f"best[ext=mp4][filesize<{TG_LIMIT_MB}M]/best[ext=mp4]/best",
        "http_headers": HEADERS,
        "nocheckcertificate": True,
        "retries": 3, "quiet": True, "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info)), info.get("title", "")


busy = False


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cache = load_cache()
    elig = eligible(cache)
    await update.message.reply_text(
        f"جاهز.\nكاش: {len(cache)} فيديو، {len(elig)} مؤهل.\n\n"
        f"/vid — فيديو واحد\n/rescan — بناء الكاش\n/stats — إحصائيات"
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cache = load_cache()
    elig = eligible(cache)
    await update.message.reply_text(f"إجمالي: {len(cache)}\nمؤهل ({MIN_SEC}-{MAX_SEC}s): {len(elig)}")


async def _rescan_bg(update, ctx):
    try:
        cache = await asyncio.to_thread(build_cache_sync)
        elig = eligible(cache)
        await update.message.reply_text(f"تم.\nإجمالي: {len(cache)}\nمؤهل: {len(elig)}")
    except Exception as e:
        await update.message.reply_text(f"فشل rescan: {type(e).__name__}: {e}")


async def cmd_rescan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text("ببدأ أسحب…")
    asyncio.create_task(_rescan_bg(update, ctx))


async def cmd_vid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global busy
    if update.effective_user.id != OWNER_ID:
        return
    if busy:
        await update.message.reply_text("شغال على واحد، استنى.")
        return

    cache = load_cache()
    if not cache:
        await update.message.reply_text("الكاش فاضي. ابعت /rescan.")
        return

    pool = eligible(cache)
    if not pool:
        await update.message.reply_text("مفيش فيديو مؤهل. ابعت /rescan.")
        return

    picked = random.choice(pool)
    busy = True
    try:
        await update.message.reply_text(f"بحمّل: {picked['dur']}s ...")
        path, title = await asyncio.to_thread(download_one, picked["url"])
        size_mb = path.stat().st_size / 1024 / 1024
        if size_mb >= TG_LIMIT_MB:
            await update.message.reply_text(f"{size_mb:.1f}MB — أكبر من السقف. بتخطاه.")
            path.unlink(missing_ok=True)
            return
        with open(path, "rb") as f:
            await update.message.reply_video(
                f, caption=title[:200] or "فيديو",
                duration=picked["dur"], supports_streaming=True,
            )
        path.unlink(missing_ok=True)
    except Exception as e:
        await update.message.reply_text(f"خطأ: {type(e).__name__}: {e}")
    finally:
        busy = False


if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("vid", cmd_vid))
    app.add_handler(CommandHandler("video", cmd_vid))
    app.add_handler(CommandHandler("rescan", cmd_rescan))
    app.add_handler(CommandHandler("stats", cmd_stats))
    print("[*] bot up")
    app.run_polling()