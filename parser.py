import argparse
import asyncio
import csv
import random
import time
import re
import aiohttp
import async_timeout
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from typing import List, Optional, Tuple

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
        # fallback to utf-8/apparent
        try:
            return content.decode("utf-8", errors="strict")
        except Exception:
            return content.decode("utf-8", errors="replace")
    except Exception:
        # last resort
        return content.decode("utf-8", errors="replace")


def _digits_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    d = re.sub(r"[^\d]", "", str(s))
    try:
        return int(d) if d else None
    except Exception:
        return None


def _parse_price(text: Optional[str]) -> Tuple[str, Optional[int]]:
    if not text:
        return ("N/A", None)
    t = str(text).strip()
    t = t.replace("\u00A0", " ").replace("\xa0", " ")
    if re.search(r'(договорн|по запросу|обсужд)', t, flags=re.I):
        return (t, None)
    nums = re.findall(r'(\d[\d\s]*)', t)
    if not nums:
        return (t, None)
    num = re.sub(r'\s+', '', nums[0])
    try:
        return (t, int(num))
    except Exception:
        return (t, None)


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
    m3 = re.search(r'(\d{2,4})\s*л\b', t, flags=re.I)
    if m3:
        try:
            return int(m3.group(1))
        except Exception:
            return None
    return None


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
    for tag in soup.select("strong, b, span"):
        try:
            txt = tag.get_text(" ", strip=True)
            if ":" in txt:
                k, v = map(str.strip, txt.split(":", 1))
                kv.setdefault(_norm_key(k), v)
        except Exception:
            pass
    for li in soup.select("li"):
        try:
            txt = li.get_text(" ", strip=True)
            if ":" in txt:
                k, v = map(str.strip, txt.split(":", 1))
                kv.setdefault(_norm_key(k), v)
        except Exception:
            pass
    return kv


def _extract_equipment(soup: BeautifulSoup) -> str:
    for h in soup.select("h1,h2,h3,h4,h5,h6"):
        try:
            if "комплектац" in h.get_text(" ", strip=True).lower():
                ul = h.find_next_sibling(["ul", "ol"])
                if ul:
                    items = [li.get_text(" ", strip=True) for li in ul.select("li")]
                    if items:
                        return "; ".join(items)
                txt_block = []
                sib = h.next_sibling
                while sib and getattr(sib, "name", None) not in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    txt_block.append(getattr(sib, "get_text", lambda sep, strip: str(sib))(" ", True))
                    sib = sib.next_sibling
                if txt_block:
                    s = " ".join(txt_block).strip()
                    s = re.sub(r'\s+', ' ', s)
                    if s:
                        return s[:2000]
        except Exception:
            pass
    txt = soup.get_text(" \n", strip=True)
    m = re.search(r"Комплектация[:\s\-–—]{0,3}([^\n]{5,2000})", txt, flags=re.I)
    if m:
        items = re.split(r'[;,]\s*', m.group(1))
        return "; ".join(it.strip() for it in items if it.strip())[:2000]
    return "N/A"


def _extract_generation(title_text: str, kv: dict) -> str:
    if not title_text:
        return "N/A"
    m = re.search(r'\(([^)]+поколен|[^)]+ поколение|[IVX]{1,4})\)', title_text, flags=re.I)
    if m:
        return m.group(1).strip()
    for k in kv:
        if "поколен" in k or "поколение" in k or "поколени" in k:
            return kv[k]
    for k in kv:
        if "generation" in k:
            return kv[k]
    return "N/A"


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

    brand = "N/A"
    model = "N/A"
    crumbs = dsoup.select(".breadcrumbs a, .c-breadcrumbs a, nav.breadcrumbs a, .breadcrumb a")
    if crumbs:
        crumbs_texts = [c.get_text(" ", strip=True) for c in crumbs]
        filtered = [x for x in crumbs_texts if not re.search(r'продаж|прода|в\s+москв|в\s+санкт|город', x, flags=re.I)]
        if len(filtered) >= 2:
            brand = filtered[0]
            model = filtered[1]
        elif len(filtered) == 1:
            parts = main_title.split()
            brand = filtered[0]
            model = " ".join(parts[1:]) if len(parts) > 1 else "N/A"
    if brand == "N/A" or model == "N/A":
        parts = main_title.split()
        if parts:
            brand = parts[0]
            model = " ".join(parts[1:]) if len(parts) > 1 else "N/A"

    kv = _parse_kv_pairs(dsoup)
    generation = _extract_generation(raw_title, kv)

    psel = dsoup.select_one('[data-ftid="bull_price"]') or dsoup.select_one('.Price__value, .card__price, .css-1cn8i4y')
    price_text = psel.get_text(" ", strip=True) if psel else ""
    price, price_num = _parse_price(price_text)

    engine = None
    power = None
    for k in kv:
        if "двигател" in k or "объем двигателя" in k or "engine" in k:
            engine = kv[k]
            p = _parse_power(kv[k])
            if p:
                power = p
            break
    for k in kv:
        if "мощност" in k or "л.с." in k or "квт" in k:
            power = power or _parse_power(kv[k])
    if power is None:
        m = re.search(r'(\d{2,4})\s*(л\.?с\.?|лс|hp|квт|kW)', text, flags=re.I)
        if m:
            unit = m.group(2).lower()
            try:
                if 'кв' in unit:
                    power = int(round(int(m.group(1)) * 1.35962))
                else:
                    power = int(m.group(1))
            except Exception:
                power = None

    transmission = None
    for k in kv:
        if "короб" in k or "трансмисси" in k:
            transmission = kv[k]
            break

    drive = None
    for k in kv:
        if "привод" in k:
            drive = kv[k]
            break

    body_type = None
    for k in kv:
        if "кузов" in k or "тип кузова" in k:
            body_type = kv[k]
            break

    mileage = None
    for k in kv:
        if "пробег" in k:
            mileage = kv[k]
            break
    if not mileage:
        mkm = re.search(r'(\d[\d\s\u00A0]*км)', text)
        mileage = mkm.group(1) if mkm else "N/A"

    owners = None
    for k in kv:
        if "владельц" in k:
            owners = _digits_int(kv[k]) or kv[k]
            break
    if owners is None:
        owners = "N/A"

    steering = None
    for k in kv:
        if "руль" in k or "расположен" in k:
            steering = kv[k]
            break
    if not steering:
        m = re.search(r'(правый|левый)\s+руль', text, flags=re.I)
        if m:
            steering = m.group(1).lower()
    if not steering:
        steering = "N/A"

    equipment = _extract_equipment(dsoup)

    return {
        "brand": brand or "N/A",
        "model": model or "N/A",
        "year": year if year is not None else "N/A",
        "generation": generation or "N/A",
        "price": price or "N/A",
        "price_num": price_num if isinstance(price_num, int) else "N/A",
        "engine": engine or "N/A",
        "power_l_s": power if power is not None else "N/A",
        "transmission": transmission or "N/A",
        "drive": drive or "N/A",
        "body_type": body_type or "N/A",
        "mileage": mileage or "N/A",
        "owners_count": owners,
        "steering": steering,
        "equipment": equipment or "N/A"
    }


async def _fetch(session: aiohttp.ClientSession, url: str, sem: asyncio.Semaphore, delay_min: float, delay_max: float) -> Optional[Tuple[str, str]]:
    async with sem:
        await asyncio.sleep(random.uniform(delay_min, delay_max))
        try:
            with async_timeout.timeout(25):
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
    # dedupe preserving order
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
    # parse in threads to avoid blocking event loop
    for idx, item in enumerate(fetched, 1):
        if item is None:
            continue
        href, text = item
        if debug:
            with open(f"debug_detail_{idx}.html", "w", encoding="utf-8") as f:
                f.write(text)
        # parse in thread
        parsed = await asyncio.to_thread(_parse_detail_from_text, href, text, debug)
        results.append(parsed)
    return results


def save_csv(items: List[dict], path: str = "drom_full.csv"):
    if not items:
        print("No items to save.")
        return
    keys = [
        "brand", "model", "year", "generation",
        "price", "price_num", "engine", "power_l_s", "transmission", "drive", "body_type",
        "mileage", "owners_count", "steering", "equipment"
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(items)
    print(f"Saved {len(items)} items to {path}")


def main_sync(pages: int, out: str, concurrency: int, delay_min: float, delay_max: float, debug: bool):
    # run async workflow
    results = asyncio.run(main_async(pages, concurrency, delay_min, delay_max, debug))
    save_csv(results, out)


async def main_async(pages: int, concurrency: int, delay_min: float, delay_max: float, debug: bool) -> List[dict]:
    print("Collecting listing pages...")
    links = await collect_links(pages, max(2, concurrency // 2), delay_min, delay_max, debug)
    print(f"Collected links: {len(links)}")
    if not links:
        return []
    print("Fetching and parsing detail pages...")
    results = await fetch_and_parse_details(links, concurrency, delay_min, delay_max, debug)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="drom.ru async detailed parser (GPU not applicable for HTTP IO)")
    parser.add_argument("--pages", type=int, default=2, help="pages to scan (listing pages)")
    parser.add_argument("--out", type=str, default="drom_full.csv", help="output csv")
    parser.add_argument("--concurrency", type=int, default=6, help="concurrent detail fetches (tune 4-12)")
    parser.add_argument("--delay-min", type=float, default=0.5, help="min per-request delay (seconds)")
    parser.add_argument("--delay-max", type=float, default=1.5, help="max per-request delay (seconds)")
    parser.add_argument("--debug", action="store_true", help="save debug html")
    args = parser.parse_args()

    main_sync(args.pages, args.out, args.concurrency, args.delay_min, args.delay_max, args.debug)