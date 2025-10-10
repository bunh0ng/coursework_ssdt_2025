# ...existing code...
import argparse
import asyncio
import csv
import random
import re
from typing import List, Optional, Tuple

import aiohttp
import async_timeout
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/115.0.0.0 Safari/537.36"
}
DROM_BASE = "https://auto.drom.ru/all/page{}/"


def _ensure_text_bytes(content: bytes, headers: dict) -> str:
    try:
        ct = headers.get("content-type", "").lower()
        if "windows-1251" in ct or "cp1251" in ct:
            return content.decode("cp1251", errors="replace")
        snippet = content[:2000].decode("latin1", errors="ignore").lower()
        if "charset=windows-1251" in snippet:
            return content.decode("cp1251", errors="replace")
        try:
            return content.decode("utf-8", errors="strict")
        except Exception:
            return content.decode("utf-8", errors="replace")
    except Exception:
        return content.decode("utf-8", errors="replace")


def _digits_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    d = re.sub(r"[^\d]", "", str(s))
    try:
        return int(d) if d else None
    except Exception:
        return None


def _parse_price(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    t = str(text).strip().replace("\u00A0", " ").replace("\xa0", " ")
    if re.search(r'(договорн|по запросу|обсужд)', t, flags=re.I):
        return None
    nums = re.findall(r'(\d[\d\s]*)', t)
    if not nums:
        return None
    num = re.sub(r'\s+', '', nums[0])
    try:
        return int(num)
    except Exception:
        return None


def _parse_power(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    t = str(text)
    m = re.search(r'(\d{2,4})\s*(л\.?с\.?|лс|hp)', t, flags=re.I)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    m2 = re.search(r'(\d{2,4})\s*(kW|кВт)', t, flags=re.I)
    if m2:
        try:
            kw = int(m2.group(1))
            return int(round(kw * 1.35962))
        except Exception:
            return None
    return None


def _parse_engine(engine_text: Optional[str]) -> Tuple[Optional[str], Optional[float]]:
    """(fuel_type, displacement_l)"""
    if not engine_text:
        return None, None
    s = engine_text.lower()
    fuel = None
    if re.search(r'бензин|petrol', s):
        fuel = "бензин"
    elif re.search(r'дизел|дизель|diesel', s):
        fuel = "дизель"
    elif re.search(r'электр|electric', s):
        fuel = "электро"
    elif re.search(r'гибрид|hybrid', s):
        fuel = "гибрид"
    else:
        # fallback first word
        m0 = re.match(r'([а-яa-z]+)', s)
        if m0:
            fuel = m0.group(1)

    m = re.search(r'(\d+[.,]?\d*)\s*(л|l)\b', s)
    if m:
        try:
            return fuel, float(m.group(1).replace(',', '.'))
        except Exception:
            pass
    m2 = re.search(r'(\d{3,4})\s*см', s)
    if m2:
        try:
            return fuel, round(int(m2.group(1)) / 1000.0, 2)
        except Exception:
            pass
    # fallback: numbers like 16 may mean 1.6 -> ignore
    return fuel, None


def _norm_key(k: Optional[str]) -> str:
    if not k:
        return ""
    return re.sub(r'[\s\:\u00A0]+', ' ', k.strip().lower())


def _parse_kv_pairs(soup: BeautifulSoup) -> dict:
    kv = {}
    for dt in soup.select("dt"):
        try:
            k = _norm_key(dt.get_text(" ", strip=True))
            dd = dt.find_next_sibling("dd")
            if dd and k:
                kv.setdefault(k, dd.get_text(" ", strip=True))
        except Exception:
            pass
    for tr in soup.select("tr"):
        try:
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                k = _norm_key(cells[0].get_text(" ", strip=True))
                v = cells[1].get_text(" ", strip=True)
                if k:
                    kv.setdefault(k, v)
        except Exception:
            pass
    # li and strong/b tags key:value
    for tag in soup.select("li, strong, b, span"):
        try:
            txt = tag.get_text(" ", strip=True)
            if ":" in txt:
                k, v = map(str.strip, txt.split(":", 1))
                kv.setdefault(_norm_key(k), v)
        except Exception:
            pass
    return kv


def _extract_equipment(soup: BeautifulSoup) -> Optional[str]:
    # Prefer explicit section
    for h in soup.select("h1,h2,h3,h4,h5,h6"):
        try:
            if "комплектац" in h.get_text(" ", strip=True).lower():
                ul = h.find_next_sibling(["ul", "ol"])
                if ul:
                    items = [li.get_text(" ", strip=True) for li in ul.select("li")]
                    if items:
                        return "; ".join(items)
                # short fallback text after header
                sib = h.next_sibling
                text_parts = []
                while sib and getattr(sib, "name", None) not in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    text_parts.append(getattr(sib, "get_text", lambda *a: str(sib))(" ", True))
                    sib = sib.next_sibling
                if text_parts:
                    s = " ".join(text_parts).strip()
                    return re.sub(r'\s+', ' ', s)[:2000]
        except Exception:
            pass
    # fallback search kv "комплектация" or "комплектация и опции"
    txt = soup.get_text(" \n", strip=True)
    m = re.search(r"Комплектация[:\s\-–—]{0,3}([^\n]{5,2000})", txt, flags=re.I)
    if m:
        items = re.split(r'[;,]\s*', m.group(1))
        return "; ".join(it.strip() for it in items if it.strip())[:2000]
    return None


def _extract_generation(title_text: str, kv: dict) -> Tuple[Optional[int], bool]:
    """Return (generation_number or None, restyling flag)."""
    restyling = False
    gen = None
    if title_text:
        # check roman numerals or digits in parentheses
        m = re.search(r'\b(I{1,4}|V?I{0,3}|[12]\d)\b\s*покол', title_text, flags=re.I)
        if m:
            # try digits
            d = re.search(r'(\d+)', m.group(0))
            if d:
                gen = int(d.group(1))
        m2 = re.search(r'\bпоколен(?:ие)?\b[^\d]{0,10}(\d+)', title_text, flags=re.I)
        if m2:
            gen = int(m2.group(1))
        if re.search(r'рестайл|рестайл', title_text, flags=re.I):
            restyling = True
    # check kv keys
    for k, v in kv.items():
        if "поколен" in k or "поколение" in k:
            d = re.search(r'(\d+)', str(v))
            if d:
                gen = int(d.group(1))
            if re.search(r'рестайл|рестайл', str(v), flags=re.I):
                restyling = True
        if "рестайл" in k or "рестайлинг" in k:
            restyling = True
    return gen, restyling


def _clean_title_for_brand_model(raw_title: str) -> Tuple[str, Optional[int]]:
    t = re.sub(r'^\s*(продажа|продаю|продается|продам|продаю:?)\b[\s\:\-–—]*', '', raw_title, flags=re.I).strip()
    y_match = re.search(r'(\b19\d{2}\b|\b20\d{2}\b)', t)
    year = int(y_match.group(0)) if y_match else None
    if y_match:
        t = re.sub(re.escape(y_match.group(0)) + r'.*$', '', t).strip()
    t = re.sub(r'\bгод\b[^\.,\-]*', '', t, flags=re.I)
    t = re.sub(r'\bв\s+[А-Яа-яA-Za-z\-\s]{2,30}\b', '', t, flags=re.I).strip()
    main_title = re.sub(r'[\s,\-–—:]+', ' ', t).strip()
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
        crumbs_texts = [c.get_text(" ", strip=True) for c in crumbs]
        filtered = [x for x in crumbs_texts if not re.search(r'продаж|прода|в\s+москв|город', x, flags=re.I)]
        if len(filtered) >= 2:
            brand = filtered[-2]
            model = filtered[-1]
    if not brand or not model:
        parts = main_title.split()
        if parts:
            brand = parts[0]
            model = " ".join(parts[1:]) if len(parts) > 1 else None

    kv = _parse_kv_pairs(dsoup)

    # generation and restyling
    generation, restyling = _extract_generation(raw_title, kv)

    # price
    psel = dsoup.select_one('[data-ftid="bull_price"]') or dsoup.select_one('.Price__value, .card__price, .css-1cn8i4y')
    price = None
    if psel:
        price = _parse_price(psel.get_text(" ", strip=True))
    # fallback meta
    if price is None:
        meta = dsoup.find("meta", {"property": "og:description"})
        if meta and meta.get("content"):
            price = _parse_price(meta["content"])

    # engine -> fuel and volume
    engine_text = None
    for k, v in kv.items():
        if "двигател" in k or "объем" in k or "engine" in k:
            engine_text = v
            break
    if not engine_text:
        m = re.search(r'(бензин|дизель|электр|гибрид)[^,;\n]{0,30}', text, flags=re.I)
        engine_text = m.group(0) if m else None
    fuel_t, engine_volume = _parse_engine(engine_text)

    # power hp
    power = None
    # check kv values likely containing power
    for k, v in kv.items():
        if "мощност" in k or "л.с." in k or "квт" in k:
            power = _parse_power(v) or power
    if power is None:
        power = _parse_power(engine_text) or _parse_power(text)

    # transmission
    transmission = None
    for k, v in kv.items():
        if "короб" in k or "трансмисси" in k:
            transmission = v
            break

    # drive
    drive = None
    for k, v in kv.items():
        if "привод" in k:
            drive = v
            break
    if not drive:
        m = re.search(r'\b(передний|задний|полный|4x4|4wd|awd)\b', text, flags=re.I)
        if m:
            drive = m.group(1).lower()

    # body type
    body_type = None
    for k, v in kv.items():
        if "кузов" in k or "тип кузова" in k:
            body_type = v
            break
    if not body_type:
        m = re.search(r'\b(седан|хэтчбек|универсал|внедорожник|джип|купе|минивэн|фургон)\b', text, flags=re.I)
        if m:
            body_type = m.group(1).lower()

    # mileage
    mileage = None
    for k, v in kv.items():
        if "пробег" in k:
            mileage = _digits_int(v)
            if mileage is not None:
                break
    if mileage is None:
        mkm = re.search(r'(\d[\d\s\u00A0]*)\s*км', text)
        if mkm:
            mileage = _digits_int(mkm.group(1))
    if mileage is None:
        mileage = None

    # owners
    owners = None
    for k, v in kv.items():
        if "владельц" in k:
            owners = _digits_int(v)
            break

    # steering
    steering = None
    for k, v in kv.items():
        if "руль" in k or "расположен" in k:
            steering = v
            break
    if not steering:
        m = re.search(r'\b(правый|левый)\b.*руль', text, flags=re.I)
        if m:
            steering = m.group(1).lower()
    if steering:
        if "прав" in steering:
            steering = "правый"
        elif "лев" in steering:
            steering = "левый"

    # equipment
    equipment = _extract_equipment(dsoup)
    # sometimes equipment appears as modification string in title/meta
    if not equipment:
        # try to find "комплектация/модификация" kv
        for k, v in kv.items():
            if "комплектац" in k or "модифик" in k or "модификация" in k:
                equipment = v
                break
    if not equipment:
        # try to extract short model spec from title like "1.6 MT Comfort"
        m = re.search(r'(\d+[.,]?\d*\s*(л|l)\b[^\n,;]{0,30})', raw_title, flags=re.I)
        if m:
            equipment = m.group(1).strip()

    # final normalization to match requested types
    return {
        "brand": brand or "N/A",
        "model": model or "N/A",
        "year": int(year) if year else "N/A",
        "generation": int(generation) if generation else "N/A",
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
        await asyncio.sleep(random.uniform(delay_min, delay_max))
        try:
            async with async_timeout.timeout(25):
                async with session.get(url) as resp:
                    content = await resp.read()
                    text = _ensure_text_bytes(content, dict(resp.headers))
                    return url, text
        except Exception as e:
            print(f" fetch error {url}: {e}")
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
        if res is None:
            continue
        _, text = res
        soup = BeautifulSoup(text, "html.parser")
        anchors = soup.select('a[data-ftid="bull_title"]')
        if not anchors:
            anchors = [a for a in soup.find_all("a", href=True) if "/cars/" in a["href"] or "/avtomobili/" in a["href"]]
        for a in anchors:
            href = a.get("href")
            if href:
                links.append(urljoin("https://auto.drom.ru", href))
    seen = set()
    links = [x for x in links if not (x in seen or seen.add(x))]
    return links


async def fetch_and_parse_details(links: List[str], concurrency: int, delay_min: float, delay_max: float, debug: bool) -> List[dict]:
    sem = asyncio.Semaphore(concurrency)
    conn = aiohttp.TCPConnector(limit_per_host=concurrency, ssl=False)
    async with aiohttp.ClientSession(headers=HEADERS, connector=conn) as session:
        tasks = [asyncio.create_task(_fetch(session, link, sem, delay_min, delay_max)) for link in links]
        fetched = await asyncio.gather(*tasks)
    results = []
    for idx, item in enumerate(fetched, 1):
        if item is None:
            continue
        href, text = item
        if debug:
            with open(f"debug_detail_{idx}.html", "w", encoding="utf-8") as f:
                f.write(text)
        parsed = await asyncio.to_thread(_parse_detail_from_text, href, text, debug)
        results.append(parsed)
    return results


def save_csv(items: List[dict], path: str = "./datasets/drom_full.csv"):
    if not items:
        print("No items to save.")
        return
    keys = [
        "brand", "model", "year", "generation", "restyling",
        "price", "engine_volume", "fuel_t", "power_hp", "transmission", "drive", "body-type",
        "mileage", "owners", "steering", "equipment"
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(items)
    print(f"Saved {len(items)} items to {path}")


def main_sync(pages: int, out: str, concurrency: int, delay_min: float, delay_max: float, debug: bool):
    results = asyncio.run(main_async(pages, concurrency, delay_min, delay_max, debug))
    save_csv(results, out)


async def main_async(pages: int, concurrency: int, delay_min: float, delay_max: float, debug: bool) -> List[dict]:
    from datetime import datetime
    print(f"{datetime.now()} Collecting listing pages...")
    links = await collect_links(pages, max(2, concurrency // 2), delay_min, delay_max, debug)
    print(f"{datetime.now()} Collected links: {len(links)}")
    if not links:
        return []
    print(f"{datetime.now()} Fetching and parsing detail pages...")
    results = await fetch_and_parse_details(links, concurrency, delay_min, delay_max, debug)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="drom.ru async parser (minimal non-numeric features)")
    parser.add_argument("--pages", type=int, default=500, help="pages to scan (listing pages)")
    parser.add_argument("--out", type=str, default="./datasets/drom_full.csv", help="output csv")
    parser.add_argument("--concurrency", type=int, default=6, help="concurrent fetches")
    parser.add_argument("--delay-min", type=float, default=0.5, help="min per-request delay (s)")
    parser.add_argument("--delay-max", type=float, default=1.5, help="max per-request delay (s)")
    parser.add_argument("--debug", action="store_true", help="save debug html")
    args = parser.parse_args()

    main_sync(args.pages, args.out, args.concurrency, args.delay_min, args.delay_max, args.debug)
# ...existing code...