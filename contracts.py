import os
import re
import sys
import random
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ======== LOG AYARLARI ========
def log_success(msg):
    print(f"\033[92m✅ {msg}\033[0m", flush=True)

def log_error(msg):
    print(f"\033[91m❌ {msg}\033[0m", flush=True)

def log_info(msg):
    print(f"\033[94mℹ️ {msg}\033[0m", flush=True)

# ======== ENV AYARLARI ========
api_id = int(os.environ["API_ID"])
api_hash = os.environ["API_HASH"]
session_string = os.environ["SESSION_STRING"]

TARGET_CHANNEL_ID = '@lapad_announcement'
BANNER_PATH = "banner.jpg"
FONTS_DIR = "fonts"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)",
    "Mozilla/5.0 (Linux; Android 10; SM-G975F)"
]

CHANNEL_PARSERS = {
    -1001292331458: 'parse_cmclistingstg',
    -1002697302809: 'parse_combo_parser',
    -1001559069277: 'parse_cmclistingstg',
    -1001873505928: 'parse_trending_scrape',
}

client = TelegramClient(StringSession(session_string), api_id, api_hash)

# ======== YARDIMCI ========
def human_format(num):
    try:
        num = float(num)
        for unit in ['', 'K', 'M', 'B', 'T']:
            if abs(num) < 1000.0:
                return f"{num:3.2f}{unit}"
            num /= 1000.0
        return f"{num:.1f}P"
    except Exception:
        return str(num)

def extract_contract_candidates(text):
    evm_regex = r'0x[a-fA-F0-9]{40}'
    general_regex = r'\b[a-zA-Z0-9]{32,}\b'
    evm_matches = re.findall(evm_regex, text)
    general_matches = [m for m in re.findall(general_regex, text) if not m.startswith('0x')]
    return evm_matches + general_matches

def extract_token_from_url(url):
    match = re.search(r'(0x[a-fA-F0-9]{40})|([A-Za-z0-9]{32,45})', url)
    return match.group(0) if match else None

def parse_cmclistingstg(text):
    lines = text.strip().splitlines()
    contracts = []
    for i, line in enumerate(lines):
        if 'CA' in line or 'Contract' in line:
            contracts += extract_contract_candidates(line)
            for j in range(1, 4):
                if i + j < len(lines):
                    contracts += extract_contract_candidates(lines[i + j])
            break
    return list(set(contracts))

def parse_trending_scrape(event):
    contracts, urls = [], []
    if event.message.entities:
        for entity in event.message.entities:
            if hasattr(entity, 'url') and entity.url:
                urls.append(entity.url)
    urls += re.findall(r'(https?://[^\s]+)', event.message.message or "")
    for url in urls:
        if any(x in url for x in ['solscan.io', 'etherscan.io', 'dexscreener.com', 'dexview.com', 'x.com', 'twitter.com']):
            token = extract_token_from_url(url)
            if token:
                contracts.append(token)
                break
    return list(set(contracts))

def parse_combo_parser(event):
    text = event.message.message or ""
    return list(set(parse_cmclistingstg(text) + parse_trending_scrape(event)))

def fetch_token_info(token_address):
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    url = f"https://api.dexscreener.com/latest/dex/search/?q={token_address}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        return r.json().get("pairs", [])
    except Exception as e:
        log_error(f"API Hatası: {e}")
        return None

def parse_social_links(pair_info):
    info = pair_info.get("info", {}) or {}
    inline_links = []
    twitter_username = ""
    socials = info.get("socials", [])
    if isinstance(socials, list):
        for s in socials:
            url = s.get("url")
            stype = (s.get("type") or "").lower()
            if url:
                if stype == "twitter":
                    parsed = re.search(r'(?:twitter\.com|x\.com)/([A-Za-z0-9_]+)', url)
                    if parsed:
                        twitter_username = f"@{parsed.group(1)}"
                        inline_links.append(f"<a href='{url}'>🐦 Twitter</a>")
                elif stype == "telegram":
                    inline_links.append(f"<a href='{url}'>💬 Telegram</a>")
                elif stype:
                    inline_links.append(f"<a href='{url}'>📢 {stype.capitalize()}</a>")
                else:
                    inline_links.append(f"<a href='{url}'>🔗 Link</a>")
    websites = info.get("websites", [])
    if isinstance(websites, list):
        for site in websites:
            if isinstance(site, dict):
                url = site.get("url")
                label = site.get("label", "Website")
                if url:
                    inline_links.append(f"<a href='{url}'>🌐 {label}</a>")
    return " | ".join(inline_links), twitter_username

# ======== GÖRSEL ========
def _textlength(draw, text, font):
    try:
        return int(draw.textlength(text, font=font))
    except:
        return len(text) * (font.size if hasattr(font, "size") else 10)

def generate_image_banner(token_name, symbol, chain, contract, logo_url):
    try:
        if not os.path.exists(BANNER_PATH):
            log_error(f"Banner bulunamadı: {BANNER_PATH}")
            return None

        banner = Image.open(BANNER_PATH).convert("RGBA")

        log_info(f"Logo indiriliyor: {logo_url}")
        resp = requests.get(logo_url, timeout=8)
        if resp.status_code != 200:
            log_error(f"Logo indirilemedi! HTTP {resp.status_code}")
            return None
        logo = Image.open(BytesIO(resp.content)).convert("RGBA")

        try:
            font_headline = ImageFont.truetype(os.path.join(FONTS_DIR, "arialbd.ttf"), size=52)
            font_token = ImageFont.truetype(os.path.join(FONTS_DIR, "arialbd.ttf"), size=46)
            font_chain = ImageFont.truetype(os.path.join(FONTS_DIR, "arial.ttf"), size=30)
            font_contract = ImageFont.truetype(os.path.join(FONTS_DIR, "arial.ttf"), size=26)
        except Exception as e:
            log_error(f"Font yüklenemedi: {e}")
            font_headline = font_token = font_chain = font_contract = ImageFont.load_default()

        draw = ImageDraw.Draw(banner)
        headline = f"${symbol.upper()} Trending Now Worldwide"
        hx = (banner.width - _textlength(draw, headline, font_headline)) // 2
        draw.text((hx, 40), headline, font=font_headline, fill="white")

        logo_size = 300
        logo = logo.resize((logo_size, logo_size))
        mask = Image.new("L", (logo_size, logo_size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, logo_size, logo_size), fill=255)
        circular_logo = Image.new("RGBA", (logo_size, logo_size), (0, 0, 0, 0))
        circular_logo.paste(logo, (0, 0), mask=mask)

        banner.paste(circular_logo, ((banner.width - logo_size) // 2, 120), circular_logo)

        token_line = f"{token_name} ({symbol.upper()})"
        tx = (banner.width - _textlength(draw, token_line, font_token)) // 2
        ty = 120 + logo_size + 20
        draw.text((tx, ty), token_line, font=font_token, fill="white")

        cx = (banner.width - _textlength(draw, chain, font_chain)) // 2
        draw.text((cx, ty + font_token.size + 12), chain, font=font_chain, fill="white")

        kx = (banner.width - _textlength(draw, contract, font_contract)) // 2
        draw.text((kx, ty + font_token.size + 12 + font_chain.size + 10), contract, font=font_contract, fill="white")

        out = BytesIO()
        banner.save(out, format="PNG")
        out.name = "banner.png"
        out.seek(0)

        log_success("Görsel başarıyla oluşturuldu.")
        return out

    except Exception as e:
        log_error(f"Görsel oluşturulamadı: {e}")
        return None

# ======== MESAJ ========
def format_pair_message(pair):
    base = pair.get("baseToken", {}) or {}
    symbol = base.get("symbol", "???")
    name = base.get("name", "Unknown")
    price = pair.get("priceUsd", "N/A")
    change = pair.get("priceChange", {}).get("h24", 0)
    liquidity = human_format(pair.get("liquidity", {}).get("usd", 0))
    mcap = human_format(pair.get("fdv", 0))
    contract = base.get("address", "N/A")
    chain = (pair.get("chainId", "EVM") or "EVM").capitalize()
    info = pair.get("info", {}) or {}
    header_url = info.get("header")
    logo_url = base.get("logoUrl") or info.get("imageUrl")
    social_links, twitter_user = parse_social_links(pair)
    hashtags = f"#lapad #{symbol.upper()} #Dexscreener {twitter_user}".strip()

    message = f"""
<b>🔥 Trending Now: {name} is trending now Worldwide</b>

<b>🔗 Chain:</b> {chain}
<b>🧬 Contract:</b> <code>{contract}</code>

<b>💵 Price:</b> ${price}
<b>🤠 Mcap:</b> ${mcap}
<b>💧 Liquidity:</b> ${liquidity}
<b>📈 24H Change:</b> {change}%

{social_links}

{hashtags}
""".strip()

    media_file = None
    if logo_url:
        media_file = generate_image_banner(name, symbol, chain, contract, logo_url)

    if not media_file and header_url:
        try:
            r = requests.get(header_url, timeout=8)
            if r.status_code == 200:
                f = BytesIO(r.content)
                f.name = "banner.png"
                f.seek(0)
                media_file = f
        except Exception:
            pass

    if not media_file:
        return None, None
    return media_file, message

# ======== EVENT HANDLER ========
@client.on(events.NewMessage(chats=list(CHANNEL_PARSERS.keys())))
async def handler(event):
    chat_id = event.chat_id
    parser_name = CHANNEL_PARSERS.get(chat_id)
    parser_func = globals().get(parser_name)
    if not callable(parser_func):
        return

    try:
        tokens = parser_func(event) if 'event' in parser_func.__code__.co_varnames else parser_func(event.message.message or "")
    except Exception as e:
        log_error(f"Parser hatası: {e}")
        return

    if not tokens:
        return

    for token in tokens:
        log_info(f"Token bulundu: {token}")
        pairs = fetch_token_info(token)
        if not pairs:
            log_error("DexScreener sonucu yok.")
            continue

        for pair in pairs:
            change = pair.get("priceChange", {}).get("h24")
            liquidity_usd = pair.get("liquidity", {}).get("usd", 0) or 0
            if change is None:
                continue
            if liquidity_usd < 10000:
                log_info("Likidite düşük, atlandı.")
                continue

            media, msg = format_pair_message(pair)
            if not media or not msg:
                log_error("Medya veya mesaj oluşturulamadı.")
                break

            try:
                await client.send_file(
                    TARGET_CHANNEL_ID,
                    file=media,
                    caption=msg,
                    parse_mode="HTML",
                    link_preview=False
                )
                log_success(f"Mesaj gönderildi: {token}")
            except Exception as e:
                log_error(f"Gönderim hatası: {e}")
            break

# ======== MAIN ========
if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)  # Flush için
    log_success("Bot başlatılıyor...")
    client.start()
    client.run_until_disconnected()