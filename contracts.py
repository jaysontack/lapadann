import re
import random
import requests
import os
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# 📌 Ayarlar
api_id = int(os.environ["API_ID"])
api_hash = os.environ["API_HASH"]
session_string = os.environ["SESSION_STRING"]

TARGET_CHANNEL_ID = '@lapad_announcement'

CHANNEL_PARSERS = {
    -1001292331458: 'parse_cmclistingstg',
    -1002697302809: 'parse_combo_parser',
    -1001559069277: 'parse_cmclistingstg',
    -1001873505928: 'parse_trending_scrape',
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)",
    "Mozilla/5.0 (Linux; Android 10; SM-G975F)"
]

BANNER_PATH = "banner.jpg"
FONT_DIR = Path(__file__).parent / "fonts"

client = TelegramClient(StringSession(session_string), api_id, api_hash)

# =================== Yardımcı Fonksiyonlar ===================

def log(msg):
    print(f"[LOG] {msg}", flush=True)

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

def extract_contract_candidates(text: str):
    evm_regex = r'0x[a-fA-F0-9]{40}'
    general_regex = r'\b[a-zA-Z0-9]{32,}\b'
    evm_matches = re.findall(evm_regex, text)
    general_matches = [m for m in re.findall(general_regex, text) if not m.startswith('0x')]
    return evm_matches + general_matches

def extract_token_from_url(url: str):
    match = re.search(r'(0x[a-fA-F0-9]{40})|([A-Za-z0-9]{32,45})', url)
    return match.group(0) if match else None

def parse_cmclistingstg(text: str):
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

def fetch_token_info(token_address: str):
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    url = f"https://api.dexscreener.com/latest/dex/search/?q={token_address}"
    try:
        log(f"🔍 API'den bilgi çekiliyor: {token_address}")
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            log(f"❌ API HTTP Hatası: {r.status_code}")
            return None
        return r.json().get("pairs", [])
    except Exception as e:
        log(f"❌ API İstek Hatası: {e}")
        return None

def parse_social_links(pair_info: dict):
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
                    twitter_username = "@" + url.split("/")[-1]
                    inline_links.append(f"<a href='{url}'>🐦 Twitter</a>")
                elif stype == "telegram":
                    inline_links.append(f"<a href='{url}'>💬 Telegram</a>")
                else:
                    inline_links.append(f"<a href='{url}'>🔗 {stype.capitalize()}</a>")
    return " | ".join(inline_links), twitter_username

def _textlength(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    try:
        return draw.textlength(text, font=font)
    except AttributeError:
        return draw.textbbox((0, 0), text, font=font)[2]

def generate_image_banner(token_name, symbol, chain, contract, logo_url):
    try:
        log(f"🖼 Görsel oluşturuluyor: {token_name} ({symbol})")
        banner = Image.open(BANNER_PATH).convert("RGBA")
        width, height = banner.size

        # Fontları fonts klasöründen yükle
        try:
            font_headline = ImageFont.truetype(str(FONT_DIR / "arialbd.ttf"), size=52)
            font_token = ImageFont.truetype(str(FONT_DIR / "arialbd.ttf"), size=46)
            font_chain = ImageFont.truetype(str(FONT_DIR / "arial.ttf"), size=30)
            font_contract = ImageFont.truetype(str(FONT_DIR / "arial.ttf"), size=26)
        except Exception as e:
            log(f"❌ Font yüklenemedi: {e}")
            font_headline = font_token = font_chain = font_contract = ImageFont.load_default()

        # Logo ekleme
        resp = requests.get(logo_url, timeout=8)
        logo = Image.open(BytesIO(resp.content)).convert("RGBA").resize((300, 300))
        mask = Image.new("L", (300, 300), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 300, 300), fill=255)
        circular_logo = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        circular_logo.paste(logo, (0, 0), mask=mask)
        banner.paste(circular_logo, (width // 2 - 150, 150), circular_logo)

        # Yazılar
        draw = ImageDraw.Draw(banner)
        draw.text((50, 40), f"${symbol} Trending Now Worldwide", font=font_headline, fill="white")
        draw.text((50, 500), f"{token_name} ({symbol})", font=font_token, fill="white")
        draw.text((50, 550), chain, font=font_chain, fill="white")
        draw.text((50, 600), contract, font=font_contract, fill="white")

        out = BytesIO()
        banner.save(out, format="PNG")
        out.name = "banner.png"
        out.seek(0)
        return out
    except Exception as e:
        log(f"❌ Görsel oluşturma hatası: {e}")
        return None

def format_pair_message(pair):
    base = pair.get("baseToken", {}) or {}
    symbol = base.get("symbol", "???")
    name = base.get("name", "Unknown")
    contract = base.get("address", "N/A")
    chain = (pair.get("chainId", "EVM") or "EVM").capitalize()
    logo_url = base.get("logoUrl")

    social_links, twitter_user = parse_social_links(pair)
    hashtags = f"#lapad #{symbol} #Dexscreener {twitter_user}".strip()

    message = f"""
<b>🔥 Trending Now: {name}</b>

<b>🔗 Chain:</b> {chain}
<b>🧬 Contract:</b> <code>{contract}</code>
{social_links}

{hashtags}
"""
    media_file = generate_image_banner(name, symbol, chain, contract, logo_url) if logo_url else None
    return media_file, message

# =================== Olaylar ===================

@client.on(events.NewMessage(chats=list(CHANNEL_PARSERS.keys())))
async def handler(event):
    log(f"📩 Yeni mesaj geldi: Chat ID {event.chat_id}")
    parser_name = CHANNEL_PARSERS.get(event.chat_id)
    parser_func = globals().get(parser_name)

    try:
        tokens = parser_func(event) if 'event' in parser_func.__code__.co_varnames else parser_func(event.message.message)
    except Exception as e:
        log(f"❌ Parser hatası: {e}")
        return

    if not tokens:
        log("⚠️ Token bulunamadı, atlanıyor.")
        return

    for token in tokens:
        log(f"🔑 Token bulundu: {token}")
        pairs = fetch_token_info(token)
        if not pairs:
            log("⚠️ Dexscreener'dan veri gelmedi.")
            continue

        for pair in pairs:
            media, msg = format_pair_message(pair)
            if not media:
                log("⚠️ Görsel oluşturulamadı.")
                continue

            try:
                await client.send_file(TARGET_CHANNEL_ID, file=media, caption=msg, parse_mode="HTML", link_preview=False)
                log(f"✅ Gönderildi: {token}")
            except Exception as e:
                log(f"❌ Gönderim hatası: {e}")

if __name__ == "__main__":
    log("🚀 Bot başlatılıyor...")
    client.start()
    log("🤖 Token dedektörü çalışıyor...")
    client.run_until_disconnected()