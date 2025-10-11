# ...existing code...
import asyncio
import aiohttp
import re
import csv
import os
import random
import argparse
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/115.0.0.0 Safari/537.36"
}
DROM_BASE = "https://auto.drom.ru/all/page{}/"


def _ensure_text_bytes(content: bytes, headers: dict) -> str:
    # try to respect content-type charset, fallback to utf-8, then latin1
    ct = headers.get("content-type", "") if headers else ""
    try:
        ct = ct.lower()
    except Exception:
        ct = ""
    if "charset=windows-1251" in ct or "cp1251" in ct or "windows-1251" in ct:
        try:
            return content.decode("cp1251", errors="ignore")
        except Exception:
            pass
    # try utf-8
    try:
        return content.decode("utf-8")
    except Exception:
        try:
            return content.decode("latin1", errors="ignore")
        except Exception:
            return content.decode("utf-8", errors="ignore")


def _digits_int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    d = re.sub(r"[^\d]", "", str(s))
    if not d:
        return None
    try:
        return int(d)
    except Exception:
        return None


def _parse_price(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    t = str(text).strip().replace("\u00A0", " ").replace("\xa0", " ")
    if re.search(r'(договорн|по запросу|обсужд)', t, flags=re.I):
        return None
    # найти все числовые группы (включая пробелы внутри числа)
    nums = re.findall(r'(\d[\d\s]*)', t)
    if not nums:
        return None
    cleaned = []
    for n in nums:
        nclean = int(re.sub(r'\s+', '', n))
        cleaned.append(nclean)
    # исключить вероятные года (1900-2099)
    candidates = [n for n in cleaned if not (1900 <= n <= 2099)]
    # предпочитаем большие числа (цены), если есть - вернуть максимальный кандидát
    if candidates:
        # часто цена - самое большое число на странице
        price = max(candidates)
        # минимальное разумное значение для цены (рублей) - 1000
        if price < 1000 and len(candidates) > 1:
            # возьмём второй максимум, если первый маленький
            candidates_sorted = sorted(candidates, reverse=True)
            for c in candidates_sorted:
                if c >= 1000:
                    return c
            return candidates_sorted[0]
        return price
    # fallback: если все числа - годы, попробуем взять последний, если он не год
    last_all = cleaned[-1]
    if not (1900 <= last_all <= 2099):
        return last_all
    return None


def _parse_power(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    t = str(text)
    m = re.search(r'(\d{2,4})\s*(л\.?с\.?|лс|hp)', t, flags=re.I)
    if m:
        return int(m.group(1))
    m2 = re.search(r'(\d{2,4})\s*(kW|кВт)', t, flags=re.I)
    if m2:
        try:
            # 1 kW ≈ 1.35962 hp
            kw = int(m2.group(1))
            return int(round(kw * 1.35962))
        except Exception:
            return None
    # try bare number but ignore years and tiny numbers
    d = _digits_int(t)
    if d and 20 <= d <= 2000:
        return d
    return None


def _parse_engine(engine_text: Optional[str]) -> Tuple[Optional[str], Optional[float]]:
    """(fuel_type, displacement_l)"""
    if not engine_text:
        return None, None
    s = str(engine_text).lower()
    fuel = None
    if re.search(r'бензин|petrol|gasoline', s):
        fuel = 'benzine'
    elif re.search(r'дизел|дизель|diesel', s):
        fuel = 'diesel'
    elif re.search(r'электр|electric', s):
        fuel = 'electric'
    elif re.search(r'гибрид|hybrid', s):
        fuel = 'hybrid'
    else:
        # try common abbrev
        if 'lpg' in s or 'газ' in s:
            fuel = 'gas'
    m = re.search(r'(\d+[.,]?\d*)\s*(л|l)\b', s)
    if m:
        try:
            vol = float(m.group(1).replace(',', '.'))
            return fuel, vol
        except Exception:
            pass
    m2 = re.search(r'(\d{3,4})\s*см', s)
    if m2:
        try:
            vol = int(m2.group(1)) / 1000.0
            return fuel, vol
        except Exception:
            pass
    return fuel, None


def _norm_key(k: Optional[str]) -> str:
    if not k:
        return ""
    return re.sub(r'[\s\:\u00A0]+', ' ', k.strip().lower())


def _parse_kv_pairs(soup: BeautifulSoup) -> dict:
    kv = {}
    # dt/dd pairs
    for dt in soup.select("dt"):
        try:
            key = _norm_key(dt.get_text(" ", strip=True))
            dd = dt.find_next_sibling("dd")
            val = dd.get_text(" ", strip=True) if dd else ""
            if key:
                kv[key] = val
        except Exception:
            continue
    # table rows
    for tr in soup.select("tr"):
        tds = tr.find_all(["th", "td"])
        if len(tds) >= 2:
            key = _norm_key(tds[0].get_text(" ", strip=True))
            val = tds[1].get_text(" ", strip=True)
            if key:
                kv[key] = val
    # simple "ключ: значение" in li or p
    for tag in soup.select("li, p, span"):
        txt = tag.get_text(" ", strip=True)
        if ':' in txt:
            parts = txt.split(':', 1)
            key = _norm_key(parts[0])
            val = parts[1].strip()
            if key and key not in kv:
                kv[key] = val
    return kv


def _extract_equipment(soup: BeautifulSoup) -> Optional[str]:
    # Prefer explicit section
    # often equipment is in .complectation or under header "Комплектация"
    for header in soup.select("h2, h3, h4"):
        htxt = header.get_text(" ", strip=True).lower()
        if "комплектац" in htxt or "комплектация" in htxt or "оборудовани" in htxt:
            nxt = header.find_next_sibling()
            if nxt:
                return nxt.get_text(" \n", strip=True)
    txt = soup.get_text(" \n", strip=True)
    m = re.search(r"Комплектация[:\s\-–—]{0,3}([^\n]{5,2000})", txt, flags=re.I)
    if m:
        return m.group(1).strip()
    return None


def _extract_generation(title_text: str, kv: dict) -> Tuple[Optional[str], bool]:
    """Return (generation_number or None, restyling flag). Generation returned as string."""
    restyling = False
    gen = None
    if title_text:
        # look for "поколение 2" or "II" or "2 поколение" or "поколение: 2"
        m = re.search(r'поколен(?:ие)?[:\s\-–—]{0,3}([ivx\d]+)', title_text, flags=re.I)
        if m:
            gen = m.group(1)
        # roman numerals like II, III
        m2 = re.search(r'\b([IVX]{2,5})\b', title_text)
        if not gen and m2:
            gen = m2.group(1)
        # restyling words
        if re.search(r'рестайлинг|рестайлингом|restyling', title_text, flags=re.I):
            restyling = True
        # sometimes "II рестайлинг" etc
    # check kv for generation info
    for k, v in kv.items():
        if 'покол' in k or 'поколен' in k or 'generation' in k:
            gen = v
        if 'рестайл' in k or 'restyl' in k:
            if re.search(r'да|есть|yes|rest', str(v), flags=re.I):
                restyling = True
    if gen:
        return str(gen).strip(), bool(restyling)
    return None, bool(restyling)


def _clean_title_for_brand_model(raw_title: str) -> Tuple[str, Optional[int]]:
    if not raw_title:
        return "", None
    t = re.sub(r'^\s*(продажа|продаю|продается|продам|продаю:?)\b[\s\:\-–—]*', '', raw_title, flags=re.I).strip()
    y_match = re.search(r'(\b19\d{2}\b|\b20\d{2}\b)', t)
    year = int(y_match.group(0)) if y_match else None
    if y_match:
        t = re.sub(re.escape(y_match.group(0)), '', t)
    t = re.sub(r'\bгод\b[^\.,\-]*', '', t, flags=re.I)
    t = re.sub(r'\bв\s+[А-Яа-яA-Za-z\-\s]{2,30}\b', '', t, flags=re.I).strip()
    main_title = re.sub(r'[\s,\-–—:]+', ' ', t).strip()
    # attempt to split first token(s) as brand/model
    parts = main_title.split()
    if len(parts) >= 2:
        brand = parts[0]
        model = " ".join(parts[1:3]) if len(parts) >= 3 else parts[1]
        return f"{brand} {model}", year
    return main_title, year


def _parse_detail_from_text(href: str, text: str, debug: bool = False) -> dict:
    dsoup = BeautifulSoup(text, "html.parser")

    title_el = dsoup.select_one('h1') or dsoup.select_one('[data-ftid="bull_title"]') or dsoup.select_one('.offer-title')
    raw_title = title_el.get_text(" ", strip=True) if title_el else ""
    main_title, year = _clean_title_for_brand_model(raw_title)

    # brand/model via breadcrumbs preferred
    brand = None
    model = None
    crumbs = dsoup.select(".breadcrumbs a, .c-breadcrumbs a, nav.breadcrumbs a, .breadcrumb a")
    if crumbs:
        txts = [c.get_text(" ", strip=True) for c in crumbs]
        # try last two meaningful crumbs
        meaningful = [t for t in txts if t and not re.search(r'продажа|авто|все', t, flags=re.I)]
        if len(meaningful) >= 2:
            brand = meaningful[-2]
            model = meaningful[-1]
    if not brand or not model:
        # fallback to main_title split
        if main_title:
            parts = main_title.split()
            if parts:
                brand = parts[0]
                model = " ".join(parts[1:3]) if len(parts) > 1 else None

    kv = _parse_kv_pairs(dsoup)

    # generation and restyling
    generation, restyling = _extract_generation(raw_title, kv)

    # price
    psel = dsoup.select_one('[data-ftid="bull_price"]') or dsoup.select_one('.Price__value, .card__price, .css-1cn8i4y, .price')
    price = None
    if psel:
        price = _parse_price(psel.get_text(" ", strip=True))
    # fallback meta or page text
    if price is None:
        meta_price = dsoup.select_one('meta[itemprop="price"]')
        if meta_price and meta_price.get("content"):
            price = _parse_price(meta_price.get("content"))
    if price is None:
        # search whole text for price-like patterns
        alltxt = dsoup.get_text(" ", strip=True)
        price = _parse_price(alltxt)

    # engine -> fuel and volume
    engine_text = None
    for k, v in kv.items():
        if 'объем' in k or 'двигател' in k or 'engine' in k:
            engine_text = v
            break
    if not engine_text:
        # try in title/meta
        meta = dsoup.find('meta', attrs={"name": "description"})
        if meta and meta.get("content"):
            engine_text = meta.get("content")
    fuel_t, engine_volume = _parse_engine(engine_text)

    # power hp
    power = None
    for k, v in kv.items():
        if 'мощн' in k or 'л.с' in k or 'hp' in k:
            power = _parse_power(v)
            break
    if power is None:
        # search text
        power = _parse_power(dsoup.get_text(" ", strip=True))

    # transmission
    transmission = None
    for k, v in kv.items():
        if 'короб' in k or 'transmiss' in k:
            transmission = v
            break

    # drive
    drive = None
    for k, v in kv.items():
        if 'привод' in k:
            drive = v
            break
    if not drive:
        txt = dsoup.get_text(" ", strip=True)
        m = re.search(r'\b(передний|перед|полн|полный|задний|4x4|awd|fwd|rwd)\b', txt, flags=re.I)
        if m:
            drive = m.group(1)

    # body type
    body_type = None
    for k, v in kv.items():
        if "кузов" in k or "тип кузова" in k or "body" in k:
            body_type = v
            break
    if not body_type:
        txt = dsoup.get_text(" ", strip=True)
        m = re.search(r'\b(седан|хэтчбек|хэтч|универсал|универал|универс|внедорожник|джип|купе|минивэн|минивен|фургон|фургон|пикап|кабриолет|кабріолет|лифтбек|лимузин|родстер)\b', txt, flags=re.I)
        if m:
            body_type = m.group(1).lower()

    # normalize
    if body_type:
        bt = body_type.lower().strip()
        bt = re.sub(r'[^а-яa-z0-9\- ]', '', bt)
        mapping = {
            'хэтч': 'хэтчбек',
            'хэтчбек': 'хэтчбек',
            'седан': 'седан',
            'универсал': 'универсал',
            'универс': 'универсал',
            'универал': 'универсал',
            'внедорожник': 'внедорожник',
            'джип': 'внедорожник',
            'купе': 'купе',
            'минивэн': 'минивэн',
            'минивен': 'минивэн',
            'фургон': 'фургон',
            'пикап': 'пикап',
            'кабриолет': 'кабриолет',
            'лифтбек': 'лифтбек',
            'лимузин': 'лимузин',
            'родстер': 'родстер'
        }
        if bt in mapping:
            body_type = mapping[bt]
        else:
            for kmap, vmap in mapping.items():
                if kmap in bt:
                    body_type = vmap
                    break

    # mileage
    mileage = None
    for k, v in kv.items():
        if 'пробег' in k:
            mileage = _digits_int(v)
            break
    if mileage is None:
        m = re.search(r'(\d[\d\s]{2,})\s*км', dsoup.get_text(" ", strip=True), flags=re.I)
        if m:
            mileage = int(re.sub(r'\s+', '', m.group(1)))

    # owners
    owners = None
    for k, v in kv.items():
        if 'владельц' in k or 'владельцев' in k:
            owners = _digits_int(v)
            break

    # steering
    steering = None
    for k, v in kv.items():
        if 'руль' in k or 'рул' in k:
            steering = v
            break
    if not steering:
        txt = dsoup.get_text(" ", strip=True)
        m = re.search(r'\b(левый|правый)\b', txt, flags=re.I)
        if m:
            steering = m.group(1)

    # equipment
    equipment = _extract_equipment(dsoup)
    if not equipment:
        # as last resort, look for modification in title
        if raw_title and len(raw_title) < 200:
            equipment = raw_title

    # final normalization to match requested types
    return {
        "url": href,
        "brand": brand or "N/A",
        "model": model or "N/A",
        "year": int(year) if year else "N/A",
        "generation": str(generation) if generation else "N/A",
        "restyling": bool(restyling),
        "price": int(price) if price else "N/A",
        "engine_volume": float(engine_volume) if engine_volume else "N/A",
        "fuel_t": fuel_t or "N/A",
        "power_hp": int(power) if power else "N/A",
        "transmission": transmission or "N/A",
        "drive": drive or "N/A",
        "body-type": body_type or "N/A",
        "mileage": int(mileage) if mileage else "N/A",
        "owners": int(owners) if owners else "N/A",
        "steering": steering or "N/A",
        "equipment": equipment or "N/A"
    }


async def _fetch(session: aiohttp.ClientSession, url: str, sem: asyncio.Semaphore, delay_min: float, delay_max: float) -> Optional[Tuple[str, str]]:
    async with sem:
        try:
            await asyncio.sleep(random.uniform(delay_min, delay_max))
            async with session.get(url, timeout=30) as resp:
                content = await resp.read()
                text = _ensure_text_bytes(content, resp.headers)
                return url, text
        except Exception as e:
            # silent skip
            return None


async def collect_links(pages: int, concurrency: int, delay_min: float, delay_max: float, debug: bool) -> List[str]:
    urls = [DROM_BASE.format(p) for p in range(1, pages + 1)]
    sem = asyncio.Semaphore(concurrency)
    conn = aiohttp.TCPConnector(limit_per_host=concurrency, ssl=False)
    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        tasks = [asyncio.create_task(_fetch(session, u, sem, delay_min, delay_max)) for u in urls]
        results = await asyncio.gather(*tasks)
    links = []
    for res in results:
        if not res:
            continue
        url, text = res
        try:
            soup = BeautifulSoup(text, "html.parser")
            # try multiple selectors known for listing items:
            candidates = set()
            for sel in ['a[data-ftid="bull_title"]', '.offer-item__title a', '.ListingItem a', '.css-1x2x2h a', 'a.offer__title', '.offer-title a', 'a.card__link', 'a[href]']:
                for a in soup.select(sel):
                    href = a.get("href")
                    if not href:
                        continue
                    href = urljoin(url, href)
                    parsed = urlparse(href)
                    # keep same domain
                    if 'drom.ru' not in parsed.netloc:
                        continue
                    # heuristics: detail pages usually contain /<something>/ and may end with id or have a title anchor
                    path = parsed.path
                    # skip listing navigation anchors
                    if re.search(r'/all/|/page', path):
                        continue
                    # keep if path contains at least two meaningful segments (brand/model/..)
                    segments = [s for s in path.split('/') if s]
                    if len(segments) >= 2:
                        candidates.add(href)
                    else:
                        # also accept if anchor text looks like a car title
                        txt = a.get_text(" ", strip=True)
                        if len(txt) > 3 and re.search(r'\d', txt) or len(txt.split()) >= 2:
                            candidates.add(href)
            links.extend(list(candidates))
        except Exception:
            continue
    # deduplicate preserving order
    seen = set()
    out = []
    for l in links:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out


async def fetch_and_parse_details(links: List[str], concurrency: int, delay_min: float, delay_max: float, debug: bool) -> List[dict]:
    sem = asyncio.Semaphore(concurrency)
    conn = aiohttp.TCPConnector(limit_per_host=concurrency, ssl=False)
    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        tasks = [asyncio.create_task(_fetch(session, l, sem, delay_min, delay_max)) for l in links]
        fetched = await asyncio.gather(*tasks)
    results = []
    for idx, item in enumerate(fetched, 1):
        if not item:
            continue
        url, text = item
        if debug:
            # save debug html
            os.makedirs("debug_html", exist_ok=True)
            fn = os.path.join("debug_html", f"page_{idx}.html")
            with open(fn, "w", encoding="utf-8") as f:
                f.write(text)
        try:
            parsed = _parse_detail_from_text(url, text, debug)
            results.append(parsed)
        except Exception:
            continue
    return results


def save_csv(items: List[dict], path: str = "drom_full_2.csv"):
    if not items:
        print("No items to save.")
        return
    keys = [
        "url", "brand", "model", "year", "generation", "restyling",
        "price", "engine_volume", "fuel_t", "power_hp", "transmission", "drive", "body-type",
        "mileage", "owners", "steering", "equipment"
    ]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for it in items:
            row = {k: it.get(k, "N/A") for k in keys}
            writer.writerow(row)
    print(f"Saved {len(items)} items to {path}")


def main_sync(pages: int, out: str, concurrency: int, delay_min: float, delay_max: float, debug: bool):
    results = asyncio.run(main_async(pages, concurrency, delay_min, delay_max, debug))
    save_csv(results, out)


async def main_async(pages: int, concurrency: int, delay_min: float, delay_max: float, debug: bool) -> List[dict]:
    print(f"{datetime.now()} Collecting listing pages...")
    links = await collect_links(pages, max(2, concurrency // 2), delay_min, delay_max, debug)
    print(f"{datetime.now()} Collected links: {len(links)}")
    if not links:
        print("No links found. Try increasing pages/concurrency or enable --debug to inspect HTML.")
        return []
    print(f"{datetime.now()} Fetching and parsing detail pages...")
    results = await fetch_and_parse_details(links, concurrency, delay_min, delay_max, debug)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="drom.ru async parser (minimal non-numeric features)")
    parser.add_argument("--pages", type=int, default=50, help="pages to scan (listing pages)")
    parser.add_argument("--out", type=str, default="./drom_full_2.csv", help="output csv")
    parser.add_argument("--concurrency", type=int, default=6, help="concurrent fetches")
    parser.add_argument("--delay-min", type=float, default=0.5, help="min per-request delay (s)")
    parser.add_argument("--delay-max", type=float, default=1.5, help="max per-request delay (s)")
    parser.add_argument("--debug", action="store_true", help="save debug html")
    args = parser.parse_args()

    main_sync(args.pages, args.out, args.concurrency, args.delay_min, args.delay_max, args.debug)
# ...existing code...