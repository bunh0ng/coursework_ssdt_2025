# ...existing code...
import argparse
import csv
import random
import time
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
# ...existing code...

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/115.0.0.0 Safari/537.36"
}
DROM_BASE = "https://auto.drom.ru/all/page{}/"

def _ensure_text(resp):
    try:
        content = resp.content
        ct = resp.headers.get("content-type", "").lower()
        if "windows-1251" in ct or "cp1251" in ct:
            return content.decode("cp1251", errors="replace")
        snippet = content[:2000].decode("latin1", errors="ignore").lower()
        if "charset=windows-1251" in snippet:
            return content.decode("cp1251", errors="replace")
        return content.decode(resp.apparent_encoding or "utf-8", errors="replace")
    except Exception:
        return resp.text

def _digits_int(s):
    if not s:
        return None
    d = re.sub(r"[^\d]", "", str(s))
    try:
        return int(d) if d else None
    except Exception:
        return None

def _parse_price(text):
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

def _parse_power(text):
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

def _norm_key(k):
    if not k:
        return ""
    return re.sub(r'[\s\:\u00A0]+', ' ', k.strip().lower())

def _parse_kv_pairs(soup):
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

def _extract_equipment(soup):
    for h in soup.select("h1,h2,h3,h4,h5,h6"):
        try:
            if "комплектац" in h.get_text(" ", strip=True).lower():
                ul = h.find_next_sibling(["ul","ol"])
                if ul:
                    items = [li.get_text(" ", strip=True) for li in ul.select("li")]
                    if items:
                        return "; ".join(items)
                txt_block = []
                sib = h.next_sibling
                while sib and getattr(sib, "name", None) not in ("h1","h2","h3","h4","h5","h6"):
                    txt_block.append(getattr(sib, "get_text", lambda sep, strip: str(sib))( " ", True ))
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

def _extract_generation(title_text, kv):
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

def parse_drom(pages: int, delay_min: float = 1.0, delay_max: float = 3.0, debug: bool = False):
    results = []
    links = []

    for page in range(1, pages + 1):
        list_url = DROM_BASE.format(page)
        print(f"GET {list_url}")
        try:
            time.sleep(random.uniform(delay_min, delay_max))
            r = requests.get(list_url, headers=HEADERS, timeout=15)
            r.raise_for_status()
        except Exception as e:
            print(" list request failed:", e)
            break
        html = _ensure_text(r)
        if debug:
            with open(f"debug_list_{page}.html", "w", encoding="utf-8") as f:
                f.write(html)
        soup = BeautifulSoup(html, "html.parser")
        anchors = soup.select('a[data-ftid="bull_title"]')
        if not anchors:
            anchors = [a for a in soup.find_all("a", href=True) if "/cars/" in a["href"] or "/avtomobili/" in a["href"]]
        for a in anchors:
            href = a.get("href")
            if href:
                links.append(urljoin("https://auto.drom.ru", href))
    seen = set()
    links = [x for x in links if not (x in seen or seen.add(x))]
    print("Collected links:", len(links))

    for i, href in enumerate(links, 1):
        print(f"[{i}/{len(links)}] GET {href}")
        try:
            time.sleep(random.uniform(delay_min, delay_max))
            r = requests.get(href, headers=HEADERS, timeout=15)
            r.raise_for_status()
        except Exception as e:
            print(" detail request failed:", e)
            continue
        text = _ensure_text(r)
        if debug:
            fn = f"debug_detail_{i}.html"
            with open(fn, "w", encoding="utf-8") as f:
                f.write(text)
        dsoup = BeautifulSoup(text, "html.parser")

        # title -> brand/model/year
        title_el = dsoup.select_one('h1') or dsoup.select_one('[data-ftid="bull_title"]') or dsoup.select_one('.offer-title')
        raw_title = title_el.get_text(" ", strip=True) if title_el else ""
        t = re.sub(r'^\s*(продажа|продаю|продается|продам|продаю:?)\b[\s\:\-–—]*', '', raw_title, flags=re.I).strip()
        y_match = re.search(r'(\b19\d{2}\b|\b20\d{2}\b)', t)
        year = int(y_match.group(0)) if y_match else "N/A"
        if y_match:
            t = re.sub(re.escape(y_match.group(0)) + r'.*$', '', t).strip()
        t = re.sub(r'\bгод\b[^\.,\-]*', '', t, flags=re.I)
        t = re.sub(r'\bв\s+[А-Яа-яA-Za-z\-\s]{2,30}\b', '', t, flags=re.I).strip()
        main_title = re.sub(r'[\s,\-–—:]+', ' ', t).strip()

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

        price_text = ""
        psel = dsoup.select_one('[data-ftid="bull_price"]') or dsoup.select_one('.Price__value, .card__price, .css-1cn8i4y')
        if psel:
            price_text = psel.get_text(" ", strip=True)
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
                transmission = kv[k]; break

        drive = None
        for k in kv:
            if "привод" in k:
                drive = kv[k]; break

        body_type = None
        for k in kv:
            if "кузов" in k or "тип кузова" in k:
                body_type = kv[k]; break

        mileage = None
        for k in kv:
            if "пробег" in k:
                mileage = kv[k]; break
        if not mileage:
            mkm = re.search(r'(\d[\d\s\u00A0]*км)', text)
            mileage = mkm.group(1) if mkm else "N/A"
        mileage_num = _digits_int(mileage)

        owners = None
        for k in kv:
            if "владельц" in k:
                owners = _digits_int(kv[k]) or kv[k]; break
        if owners is None:
            owners = "N/A"

        steering = None
        for k in kv:
            if "руль" in k or "расположен" in k:
                steering = kv[k]; break
        if not steering:
            m = re.search(r'(правый|левый)\s+руль', text, flags=re.I)
            if m:
                steering = m.group(1).lower()
        if not steering:
            steering = "N/A"

        reg_count = None
        for k in kv:
            if "запис" in k and ("регистрац" in k or "птс" in k):
                reg_count = _digits_int(kv[k]); break
        if reg_count is None:
            m = re.search(r'запис[^\d]{0,10}(\d{1,3})', text, flags=re.I)
            if m:
                try:
                    reg_count = int(m.group(1))
                except Exception:
                    reg_count = None
        if reg_count is None:
            reg_count = "N/A"

        equipment = _extract_equipment(dsoup)

        results.append({
            "brand": brand or "N/A",
            "model": model or "N/A",
            "year": year if year != None else "N/A",
            "generation": generation or "N/A",
            "price": price or "N/A",
            "price_num": price_num if isinstance(price_num, int) else "N/A",
            "engine": engine or "N/A",
            "power_l_s": power if power is not None else "N/A",
            "transmission": transmission or "N/A",
            "drive": drive or "N/A",
            "body_type": body_type or "N/A",
            "mileage": mileage or "N/A",
            # "mileage_num": mileage_num if mileage_num is not None else "N/A",
            "owners_count": owners,
            "steering": steering,
            "equipment": equipment or "N/A"
            # "registration_records": reg_count
        })

    return results

def save_csv(items, path="drom_full.csv"):
    if not items:
        print("No items to save.")
        return
    keys = [
        "brand","model","year","generation",
        "price","price_num","engine","power_l_s","transmission","drive","body_type",
        "mileage","owners_count","steering","equipment"
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(items)
    print(f"Saved {len(items)} items to {path}")

def main():
    parser = argparse.ArgumentParser(description="drom.ru detailed parser")
    parser.add_argument("--pages", type=int, default=44300, help="pages to scan")
    parser.add_argument("--out", type=str, default="drom_full.csv", help="output csv")
    parser.add_argument("--debug", action="store_true", help="save debug html")
    args = parser.parse_args()

    items = parse_drom(args.pages, debug=args.debug)
    save_csv(items, args.out)

if __name__ == "__main__":
    main()
# ...existing code...
