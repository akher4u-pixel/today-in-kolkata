"""Fetch today's Kolkata gold, petrol and diesel prices and write rates.json and fuel.json.

Run by the GitHub Actions job. Gold and fuel are fetched independently, so one can succeed while the other fails.
"""
import html as htmllib, json, re, sys, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RATES = ROOT / "rates.json"
FUEL = ROOT / "fuel.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}
CUR = r"(?:₹|Rs\.?|INR)\s*"
NUM = r"([\d,]+(?:\.\d+)?)"


def fetch_text(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        print(f"  HTTP {r.status}, {len(raw)} bytes from {url}")
    s = raw.decode("utf-8", "ignore")
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmllib.unescape(s).replace(" ", " ")
    return re.sub(r"\s+", " ", s)


def diagnose(text, words):
    print("  First 300 characters of page text:", text[:300])
    for w in words:
        i = text.find(w)
        if i >= 0:
            print(f"  Around '{w}':", text[max(0, i - 120): i + 200])
            return
    print("  None of the expected words were found. The site may be blocking this request.")


def num(s):
    return float(s.replace(",", ""))


def today_ist():
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def load(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


# ---------------- gold ----------------
GOLD_SOURCES = [
    {"name": "Goodreturns", "url": "https://www.goodreturns.in/gold-rates/kolkata.html", "patterns": [
        rf"stands at\s*{CUR}{NUM}\s*per gram for 24 karat.*?{CUR}{NUM}\s*per gram for 22 karat.*?{CUR}{NUM}\s*per gram for 18 karat",
        rf"24K\s*22K\s*18K\s*1\s*{CUR}{NUM}\s*{CUR}{NUM}\s*{CUR}{NUM}",
        rf"24\s*(?:K|karat|carat)[^₹Rs]{{0,40}}{CUR}{NUM}.*?22\s*(?:K|karat|carat)[^₹Rs]{{0,40}}{CUR}{NUM}.*?18\s*(?:K|karat|carat)[^₹Rs]{{0,40}}{CUR}{NUM}",
    ]},
    {"name": "All India Bullion", "url": "https://allindiabullion.com/gold-rate/west-bengal/kolkata", "patterns": [
        rf"24K gold in Kolkata is\s*{CUR}{NUM}.*?22K is\s*{CUR}{NUM}.*?18K is\s*{CUR}{NUM}",
    ]},
]


def gold_ok(k24, k22, k18):
    return 5000 < k24 < 100000 and 0.85 < k22 / k24 < 0.97 and 0.7 < k18 / k24 < 0.8


def read_gold(src):
    print("Gold: trying", src["name"])
    text = fetch_text(src["url"])
    for p in src["patterns"]:
        for m in re.finditer(p, text, re.I | re.S):
            k24, k22, k18 = (round(num(x)) for x in m.groups())
            if gold_ok(k24, k22, k18):
                return {"k24": k24, "k22": k22, "k18": k18}
    diagnose(text, ("per gram", "Kolkata"))
    raise ValueError(f"{src['name']}: gold rate not found")


def update_gold():
    now = used = None
    errors = []
    for src in GOLD_SOURCES:
        try:
            now, used = read_gold(src), src
            break
        except Exception as e:
            print("  Failed:", e)
            errors.append(str(e))
    if not now:
        raise RuntimeError("; ".join(errors))
    today, old = today_ist(), load(RATES)
    prev = old.get("prev_per_gram", now)
    if old.get("date") and old["date"] != today:
        prev = old.get("per_gram", now)
    data = {"date": today, "per_gram": now, "prev_per_gram": prev, "making_percent": 12, "gst_percent": 3,
            "source_url": used["url"], "source_name": used["name"]}
    RATES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print("Gold written:", data)


# ---------------- fuel ----------------
FUEL_URLS = {"petrol": "https://www.goodreturns.in/petrol-price-in-kolkata.html",
             "diesel": "https://www.goodreturns.in/diesel-price-in-kolkata.html"}


def read_fuel(kind, url):
    print("Fuel: trying", kind)
    text = fetch_text(url)
    patterns = [
        rf"{kind} price in Kolkata stands at\s*{CUR}{NUM}\s*per litre",
        rf"{kind} (?:price|rate)[^₹Rs]{{0,60}}Kolkata[^₹Rs]{{0,60}}{CUR}{NUM}\s*(?:per litre|/ ?l|/ ?ltr)",
        rf"Kolkata[^₹Rs]{{0,80}}{kind}[^₹Rs]{{0,60}}{CUR}{NUM}",
    ]
    for p in patterns:
        for m in re.finditer(p, text, re.I | re.S):
            price = num(m.group(1))
            if 50 < price < 250:
                return price
    diagnose(text, ("per litre", "Kolkata"))
    raise ValueError(f"{kind}: price not found")


def update_fuel():
    today, old = today_ist(), load(FUEL)
    data = {"date": today}
    for kind, url in FUEL_URLS.items():
        price = read_fuel(kind, url)
        o = old.get(kind, {})
        if o and abs(o.get("price", price) - price) > 0.001:
            data[kind] = {"price": price, "prev": o["price"], "changed_on": today}
        else:
            data[kind] = {"price": price, "prev": o.get("prev", price), "changed_on": o.get("changed_on")}
    data.update({"source_url_petrol": FUEL_URLS["petrol"], "source_url_diesel": FUEL_URLS["diesel"],
                 "source_name": "Goodreturns"})
    FUEL.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print("Fuel written:", data)


if __name__ == "__main__":
    failed = []
    for name, fn in (("gold", update_gold), ("fuel", update_fuel)):
        try:
            fn()
        except Exception as e:
            print(f"ERROR ({name}):", e, file=sys.stderr)
            failed.append(name)
    sys.exit(1 if failed else 0)
