import os
import re
import random
import time
import asyncio
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from telethon import TelegramClient, events
from telethon.sessions import StringSession

def log_success(msg): print(f"\033[92m✅ {msg}\033[0m", flush=True)
def log_error(msg):   print(f"\033[91m❌ {msg}\033[0m", flush=True)
def log_info(msg):    print(f"\033[94mℹ️ {msg}\033[0m", flush=True)

api_id = int(os.environ["API_ID"])
api_hash = os.environ["API_HASH"]
session_string = os.environ["SESSION_STRING"]

TARGET_CHANNEL_ID = "@lapad_announcement"
BANNER_PATH = "banner.jpg"
FONTS_DIR = "fonts"
FALLBACK_LOGO = "lapadtrending.png"

USER_AGENTS = [
    # Masaüstü
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64)",
    # Mobil
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)",
    "Mozilla/5.0 (Linux; Android 10; SM-G975F)",
    "Mozilla/5.0 (Linux; Android 11; Pixel 5)",
    "Mozilla/5.0 (iPad; CPU OS 13_2 like Mac OS X)",
    # Tarayıcı çeşitleri
    "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0",
    "Mozilla/5.0 (Windows NT 10.0; WOW64; rv:45.0) Gecko/20100101 Firefox/45.0",
    "Mozilla/5.0 (Linux; Android 9; SAMSUNG SM-G960U)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_2 like Mac OS X)",
    "Mozilla/5.0 (Linux; Android 12; Pixel 6 Pro)",
]

CHANNEL_PARSERS = {
    -1001292331458: "parse_cmclistingstg",
    -1002697302809: "parse_combo_parser",
    -1001559069277: "parse_cmclistingstg",
    -1001873505928: "parse_trending_scrape",
}

client = TelegramClient(StringSession(session_string), api_id, api_hash)
TREND_MSG_ID = None

def human_format(num):
    try:
        num = float(num)
        for unit in ["", "K", "M", "B", "T"]:
            if abs(num) < 1000.0: return f"{num:3.2f}{unit}"
            num /= 1000.0
        return f"{num:.1f}P"
    except Exception:
        return str(num)

def extract_contract_candidates(text):
    evm_regex = r"0x[a-fA-F0-9]{40}"
    general_regex = r"\b[a-zA-Z0-9]{32,}\b"
    evm_matches = re.findall(evm_regex, text)
    general_matches = [m for m in re.findall(general_regex, text) if not m.startswith("0x")]
    return evm_matches + general_matches

def extract_token_from_url(url):
    m = re.search(r"(0x[a-fA-F0-9]{40})|([A-Za-z0-9]{32,45})", url)
    return m.group(0) if m else None

def parse_cmclistingstg(text):
    lines = text.strip().splitlines()
    contracts = []
    for i, line in enumerate(lines):
        if "CA" in line or "Contract" in line:
            contracts += extract_contract_candidates(line)
            for j in range(1, 4):
                if i + j < len(lines): contracts += extract_contract_candidates(lines[i + j])
            break
    return list(set(contracts))

def parse_trending_scrape(event):
    contracts, urls = [], []
    if event.message.entities:
        for entity in event.message.entities:
            if hasattr(entity, "url") and entity.url: urls.append(entity.url)
    urls += re.findall(r"(https?://[^\s]+)", event.message.message or "")
    for url in urls:
        if any(x in url for x in ["solscan.io", "etherscan.io", "dexscreener.com", "dexview.com", "x.com", "twitter.com"]):
            tok = extract_token_from_url(url)
            if tok: contracts.append(tok); break
    return list(set(contracts))

def parse_combo_parser(event):
    text = event.message.message or ""
    return list(set(parse_cmclistingstg(text) + parse_trending_scrape(event)))

def fetch_token_info(token_address, retries=3):
    url = f"https://api.dexscreener.com/latest/dex/search/?q={token_address}"
    for attempt in range(retries):
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 200:
                return r.json().get("pairs", [])
            log_error(f"Dexscreener error {r.status_code}, attempt {attempt+1}")
        except Exception as e:
            log_error(f"API error: {e}, attempt {attempt+1}")
        time.sleep(1 + attempt)  # progressive backoff
    return None

def parse_social_links(pair_info):
    info = pair_info.get("info", {}) or {}
    inline_links, twitter_username = [], ""
    socials = info.get("socials", [])
    if isinstance(socials, list):
        for s in socials:
            url = s.get("url"); stype = (s.get("type") or "").lower()
            if url:
                if stype == "twitter":
                    parsed = re.search(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]+)", url)
                    if parsed: twitter_username = f"@{parsed.group(1)}"; inline_links.append(f"<a href='{url}'>🐦 Twitter</a>")
                elif stype == "telegram": inline_links.append(f"<a href='{url}'>💬 Telegram</a>")
                elif stype: inline_links.append(f"<a href='{url}'>📢 {stype.capitalize()}</a>")
                else: inline_links.append(f"<a href='{url}'>🔗 Link</a>")
    websites = info.get("websites", [])
    website_url = ""
    if isinstance(websites, list):
        for site in websites:
            if isinstance(site, dict):
                url = site.get("url")
                if url and not website_url: website_url = url
    return " | ".join(inline_links), website_url, twitter_username

def _textlength(draw, text, font):
    if hasattr(draw, "textlength"): return int(draw.textlength(text, font=font))
    try: return draw.textbbox((0, 0), text, font=font)[2]
    except Exception: return len(text) * (font.size if hasattr(font, "size") else 10)

def select_best_change(changes: dict):
    best_val, best_int = None, None
    for interval in ["h1", "h6", "h24"]:
        val = changes.get(interval)
        if val is not None:
            if best_val is None or abs(val) > abs(best_val): best_val, best_int = val, interval
    return best_val, best_int

def load_fonts():
    try:
        font_headline = ImageFont.truetype(os.path.join(FONTS_DIR, "arialbd.ttf"), size=52)
        font_token    = ImageFont.truetype(os.path.join(FONTS_DIR, "arialbd.ttf"), size=42)
        font_chain    = ImageFont.truetype(os.path.join(FONTS_DIR, "arial.ttf"),  size=28)
        font_contract = ImageFont.truetype(os.path.join(FONTS_DIR, "arial.ttf"),  size=24)
        font_web      = ImageFont.truetype(os.path.join(FONTS_DIR, "arial.ttf"),  size=22)
        font_change   = ImageFont.truetype(os.path.join(FONTS_DIR, "arialbd.ttf"), size=38)
        return font_headline, font_token, font_chain, font_contract, font_web, font_change
    except Exception as e:
        log_error(f"Font load failed: {e}, fallback.")
        d = ImageFont.load_default()
        return d, d, d, d, d, d

# ---------------- Tek Token Banner ----------------
def generate_image_banner(token_name, symbol, chain, contract, logo_url, website_url, change, change_interval):
    try:
        if not os.path.exists(BANNER_PATH): log_error("Banner not found!"); return None
        banner = Image.open(BANNER_PATH).convert("RGBA")
        width, height = banner.size
        resp = requests.get(logo_url, timeout=8)
        if resp.status_code != 200: log_error("Logo download failed!"); return None
        logo = Image.open(BytesIO(resp.content)).convert("RGBA")
        font_headline, font_token, font_chain, font_contract, font_web, font_change = load_fonts()
        draw = ImageDraw.Draw(banner)
        headline = f"🟢 ${(symbol or '').upper()} <a href='https://t.me/lapad_announcement'>#Trending</a> Now Worldwide"
        hx = (width - _textlength(draw, headline, font_headline)) // 2
        draw.text((hx, 60), headline, font=font_headline, fill="white")
        logo_size = 300
        logo = logo.resize((logo_size, logo_size))
        mask = Image.new("L", (logo_size, logo_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, logo_size, logo_size), fill=255)
        circular_logo = Image.new("RGBA", (logo_size, logo_size), (0, 0, 0, 0))
        circular_logo.paste(logo, (0, 0), mask=mask)
        logo_x = (width - logo_size) // 2; logo_y = 220
        banner.paste(circular_logo, (logo_x, logo_y), circular_logo)
        if change and change > 0:
            perc_text = f"+{int(change)}%"
            perc_w = _textlength(draw, perc_text, font=font_change)
            perc_x = (width - perc_w) // 2; perc_y = logo_y - 60
            draw.text((perc_x, perc_y), perc_text, font=font_change, fill="green")
        token_line = f"{token_name} ({(symbol or '').upper()})"
        tx = (width - _textlength(draw, token_line, font_token)) // 2
        draw.text((tx, logo_y + logo_size + 40), token_line, font=font_token, fill="white")
        cx = (width - _textlength(draw, chain.upper(), font_chain)) // 2
        draw.text((cx, logo_y + logo_size + 90), chain.upper(), font=font_chain, fill="white")
        kx = (width - _textlength(draw, contract, font_contract)) // 2
        draw.text((kx, logo_y + logo_size + 130), contract, font=font_contract, fill="white")
        out = BytesIO(); banner.save(out, format="PNG"); out.name = "banner.png"; out.seek(0)
        log_success("Banner generated.")
        return out
    except Exception as e:
        log_error(f"Image error: {e}")
        return None

def format_pair_message(pair):
    base = pair.get("baseToken", {}) or {}
    symbol = base.get("symbol", "???")
    name = base.get("name", "Unknown")
    price = pair.get("priceUsd", "N/A")
    changes = pair.get("priceChange", {}) or {}
    best_change, best_int = select_best_change(changes)
    if best_change is None or best_change <= 0:  # Negatif pump yok
        return None, None
    liquidity = human_format(pair.get("liquidity", {}).get("usd", 0))
    mcap = human_format(pair.get("fdv", 0))
    contract = base.get("address", "N/A")
    chain = (pair.get("chainId", "EVM") or "EVM").capitalize()
    logo_url = base.get("logoUrl") or pair.get("info", {}).get("imageUrl")
    social_links, website_url, twitter_user = parse_social_links(pair)
    headline = f"🟢 ${(symbol or '').upper()} <a href='https://t.me/lapad_announcement'>#Trending</a> Now Worldwide"
    hashtags = f"#lapad #{(symbol or '').upper()} #Dexscreener #BullishMarketCap {twitter_user}".strip()
    message = f"""
<b>{headline}</b>

<b>🔗 Chain:</b> {chain}
<b>🧬 Contract:</b> <code>{contract}</code>

<b>💵 Price:</b> ${price}
<b>🤠 Mcap:</b> ${mcap}
<b>💧 Liquidity:</b> ${liquidity}

{social_links}

{hashtags}
""".strip()
    media_file = generate_image_banner(name, symbol, chain, contract, logo_url, website_url, best_change, best_int) if logo_url else None
    if not media_file: return None, None
    return media_file, message

# ---------------- Worldwide Banner ----------------
def chain_short(chain):
    mapping = {
    "Ethereum": "ETH",
    "Bsc": "BSC",
    "Solana": "SOL",
    "Arbitrum": "ARB",
    "Polygon": "POL",
    "Avalanche": "AVAX",
    "Fantom": "FTM",
    "Optimism": "OP",
    "Base": "BASE",
    "Tron": "TRX",
    "Cosmos": "ATOM",
    "Near": "NEAR",
    "Algorand": "ALGO",
    "Aptos": "APT",
    "Sui": "SUI",
    "Harmony": "ONE",
    "Kava": "KAVA",
    "Cronos": "CRO",
    "Celo": "CELO",
    "ZkSync": "ZKS"
}
    return mapping.get(chain, chain.upper())

def load_font_simple(size):
    try: return ImageFont.truetype("arialbd.ttf", size)
    except: return ImageFont.load_default()

def generate_worldwide_banner(tokens):
    try: banner = Image.open(BANNER_PATH).convert("RGBA")
    except: banner = Image.new("RGBA", (1000, 950), (20, 20, 30, 255))
    draw = ImageDraw.Draw(banner)
    font_headline, font_token, _, _, _, font_change = load_fonts()
    font_rank = ImageFont.truetype(os.path.join(FONTS_DIR, "arialbd.ttf"), size=32)

    title = "Worldwide Top Trends"
    tw = draw.textlength(title, font=font_headline)
    draw.text(((banner.width - tw) // 2, 30), title, font=font_headline, fill="white")

    SIZE_BIG, SIZE_SMALL = 132, 108
    cx = banner.width // 2
    cy1, cy2, cy3 = 230, 360, 600
    gap2, gap3 = 420, 380
    centers = [(cx, cy1), (cx - gap2 // 2, cy2), (cx + gap2 // 2, cy2),
               (cx - gap3, cy3), (cx, cy3), (cx + gap3, cy3)]

    def paste_circle(center, size, logo_img, gold=False):
        x = center[0] - size // 2; y = center[1] - size // 2
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        circ = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        circ.paste(logo_img, (0, 0), mask=mask)
        ring = ImageDraw.Draw(circ)
        if gold:
            ring.ellipse((2, 2, size - 2, size - 2), outline=(255, 215, 0, 255), width=6)
        else:
            ring.ellipse((2, 2, size - 2, size - 2), outline=(255, 255, 255, 255), width=4)
        banner.paste(circ, (x, y), circ)
        return x, y, size

    for idx, (chg, tf, sym, chain, logo_url, url, tw_user, tg_link) in enumerate(tokens[:6]):
        if chg <= 0: 
            continue
        size = SIZE_BIG if idx == 0 else SIZE_SMALL
        try:
            if logo_url:
                resp = requests.get(logo_url, timeout=6)
                logo = Image.open(BytesIO(resp.content)).convert("RGBA").resize((size, size))
            else:
                raise Exception("no logo")
        except:
            logo = Image.open(FALLBACK_LOGO).convert("RGBA").resize((size, size)) if os.path.exists(FALLBACK_LOGO) else Image.new("RGBA", (size, size), (80, 80, 100, 255))
        x, y, size = paste_circle(centers[idx], size, logo, gold=(idx == 0))

        rank_text = f"#{idx+1}"
        rw = draw.textlength(rank_text, font=font_rank)
        draw.text((x + (size - rw)//2, y - 38), rank_text, font=font_rank, fill="yellow")

        sym_text = f"${sym}"
        sw = draw.textlength(sym_text, font=font_token)
        draw.text((x + (size - sw)//2, y + size + 10), sym_text, font=font_token, fill="white")

        if chg > 0:
            chg_text = f"+{chg:.0f}%"
            cw = draw.textlength(chg_text, font=font_change)
            draw.text((x + (size - cw)//2, y + size + 44), chg_text, font=font_change, fill=(0,255,0,255))

    out = BytesIO(); banner.save(out, format="PNG"); out.name = "trends.png"; out.seek(0)
    return out

def build_trends_caption(tokens):
    caption = "🔥 <b>Worldwide Top #Trends Diamonds Now | Live Update</b>\n\n"
    rank = 1
    for chg, tf, sym, chain, logo_url, url, tw_user, tg_link in tokens[:8]:
        if chg <= 0: 
            continue
        link = tg_link or url or "https://dexscreener.com"
        caption += f"<b>#{rank} {sym} | {chain_short(chain)} | +{chg:.0f}%</b>\n"
        rank += 1
    caption += "\n#Dexscreener #BullishMarketCap #Trend\n"
    caption += "\n👉 <b><a href='https://t.me/Lets_Announcepad'>Join Community</a> | <a href='https://t.me/Mike_letsannouncepad'>Apply Trend Now</a></b>"
    return caption

async def collect_contracts_from_channel(limit=200):
    msgs = await client.get_messages(TARGET_CHANNEL_ID, limit=limit)
    contracts = []
    for m in msgs:
        contracts += re.findall(r"0x[a-fA-F0-9]{40}", m.message or "")
    u = list(set(contracts))
    log_info(f"Worldwide: collected {len(u)} contracts.")
    return u

async def pick_top_tokens(contracts):
    token_changes, seen_symbols = [], set()
    for token in contracts:
        pairs = fetch_token_info(token); await asyncio.sleep(1)
        if not pairs: continue
        for pair in pairs:
            change, tf = select_best_change(pair.get("priceChange", {}) or {})
            if change is None or change <= 0: continue
            base = pair.get("baseToken", {}) or {}
            symbol = base.get("symbol", "???")
            if symbol in seen_symbols: continue
            seen_symbols.add(symbol)
            logo = base.get("logoUrl") or (pair.get("info", {}) or {}).get("imageUrl")
            chain = (pair.get("chainId") or "EVM").capitalize()
            url = pair.get("url", "https://dexscreener.com")
            socials = (pair.get("info", {}) or {}).get("socials", [])
            tw_user, tg_link = None, None
            for s in socials:
                if s.get("type") == "twitter": tw_user = s.get("url")
                if s.get("type") == "telegram": tg_link = s.get("url")
            token_changes.append((change, tf, symbol, chain, logo, url, tw_user, tg_link))
    top_tokens = sorted(token_changes, key=lambda x: x[0], reverse=True)[:8]
    log_info(f"Worldwide: top token count {len(top_tokens)}.")
    return top_tokens

async def find_existing_trend_message_id():
    msgs = await client.get_messages(TARGET_CHANNEL_ID, limit=30)
    for m in msgs:
        if m.out and m.message and "Worldwide Top #Trends Diamonds Now" in m.message:
            return m.id
    return None

async def send_or_update_trends():
    global TREND_MSG_ID
    if TREND_MSG_ID is None:
        TREND_MSG_ID = await find_existing_trend_message_id()
        if TREND_MSG_ID: log_info(f"Worldwide: found existing message #{TREND_MSG_ID}.")
    contracts = await collect_contracts_from_channel(limit=220)
    tokens = await pick_top_tokens(contracts)
    if tokens:
        banner = generate_worldwide_banner(tokens)
        caption = build_trends_caption(tokens)
    else:
        banner = None
        caption = "🔥 <b>Worldwide Top #Trends Diamonds Now | Live Update</b>\n\n<i>Not enough data yet. Collecting...</i>"
        log_info("Worldwide: no data, sending placeholder.")
    if TREND_MSG_ID is None:
        msg = await client.send_message(TARGET_CHANNEL_ID, caption, parse_mode="HTML", link_preview=False)
        TREND_MSG_ID = msg.id
        log_success(f"Worldwide: first message sent #{TREND_MSG_ID}.")
    else:
        await client.edit_message(TARGET_CHANNEL_ID, TREND_MSG_ID, text=caption, parse_mode="HTML", link_preview=False)
        log_success("Worldwide: message updated.")

async def periodic_task():
    while True:
        try:
            await send_or_update_trends()
        except Exception as e:
            log_error(f"Worldwide error: {e}")
        await asyncio.sleep(3600)

@client.on(events.NewMessage(chats=list(CHANNEL_PARSERS.keys())))
async def handler(event):
    chat_id = event.chat_id
    parser_name = CHANNEL_PARSERS.get(chat_id)
    parser_func = globals().get(parser_name)
    if not callable(parser_func): return
    try:
        tokens = parser_func(event) if "event" in parser_func.__code__.co_varnames else parser_func(event.message.message or "")
    except Exception as e:
        log_error(f"Parser error: {e}")
        return
    if not tokens: return
    for token in tokens:
        log_info(f"Token found: {token}")
        pairs = fetch_token_info(token)
        if not pairs: log_error("No DexScreener result."); continue
        for pair in pairs:
            liquidity_usd = pair.get("liquidity", {}).get("usd", 0) or 0
            if liquidity_usd < 10000: log_info("Low liquidity, skipped."); continue
            media, msg = format_pair_message(pair)
            if not media or not msg: log_info("Negative or invalid, skipped."); break
            try:
                await client.send_file(TARGET_CHANNEL_ID, file=media, caption=msg, parse_mode="HTML", link_preview=False)
                log_success(f"Message sent: {token}")
            except Exception as e:
                log_error(f"Send error: {e}")
            break

if __name__ == "__main__":
    log_success("Bot starting...")
    client.start()
    client.loop.create_task(periodic_task())
    client.run_until_disconnected()
