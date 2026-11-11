"""Забирает актуальные данные салона из открытого API bimassist и пишет data.json.

Запуск: python sync.py
Если bimassist недоступен, старый data.json остаётся как есть, а сайт собирается из него.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
API = f"https://business.bimassist.ru/api/public/v1/organizations/{CFG['org_id']}"
PET_TYPES = {"dogs": 1, "cats": 2, "rabbits": 3}


def get(url: str):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (site-sync)",
        "Origin": "https://clients.bimassist.ru",
        "Referer": "https://clients.bimassist.ru/",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


IMG_HOSTS = {"bim-business.hb.bizmrg.com", "business.bimassist.ru"}


def photo(p):
    """Только https-картинки с серверов bimassist, иначе None."""
    from urllib.parse import urlparse
    url = p.get("url") if p and p.get("id") else None
    if not url:
        return None
    u = urlparse(url)
    return url if u.scheme == "https" and u.hostname in IMG_HOSTS else None


def txt(v, limit=600):
    """Строка без управляющих символов и не длиннее limit. HTML экранируется позже, при сборке."""
    s = "".join(ch for ch in str(v or "") if ch.isprintable() or ch in " \n")
    return s[:limit]


def num(v):
    """Целое неотрицательное число или ошибка: мусор в цене не должен попасть на сайт."""
    n = int(v)
    if n < 0 or n > 1_000_000:
        raise ValueError(f"подозрительное число: {v}")
    return n


def fetch() -> dict:
    org_raw = get(API)
    o = org_raw["organization"]
    office = next((x for x in org_raw["offices"] if x["id"] == CFG["office_id"]), org_raw["offices"][0])
    salon = (office.get("children") or [office])[0]
    data = {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "org": {
            "name": txt(o["name"], 80),
            "logo": photo(o.get("logo")),
            "rating": min(5.0, max(0.0, float(salon.get("rating", o.get("rating")) or 0))),
            "review_count": num(org_raw.get("review_count", 0)),
            "address": txt(salon.get("address") or office.get("address"), 200),
            "phone": "".join(ch for ch in str(salon.get("phone") or office.get("phone") or "") if ch.isdigit())[:15],
            "work_time": txt(salon.get("work_time", ""), 80),
            "about": txt(salon.get("about", ""), 400),
        },
        "employees": [],
        "services": {},
        "reviews": [],
    }
    for key, pet in PET_TYPES.items():
        j = get(f"{API}/grooming/order-process/grooming-services?pet_type_id={pet}"
                f"&office_id={office['id']}&office_type_id=0")["data"]
        groups = {g["id"]: g["name"] for g in j["grooming_service_groups"]}
        if not data["employees"]:
            data["employees"] = [{
                "name": txt(" ".join(x for x in (e["firstname"], e.get("lastname")) if x), 60),
                "role": txt(e.get("description"), 60),
                "about": txt(e.get("short_description"), 300),
                "photo": photo(e.get("photo")),
            } for e in j["employees"] if e.get("is_available_for_booking", True)]
        services = []
        all_sv = sorted(j["grooming_services"], key=lambda s: s.get("sort_index", 0))
        bookable = [s for s in all_sv if s.get("selectable") and s.get("masters")]
        if not bookable:
            # Онлайн-запись на этот вид пока не открыта: показываем услуги с записью по телефону
            services = [{"id": num(s["id"]), "name": txt(s["name"], 120), "desc": txt(s.get("description"), 600),
                         "group": groups.get(s["grooming_service_group_id"], ""), "min": None, "max": None,
                         "dmin": None, "dmax": None, "phone_only": True} for s in all_sv if s.get("pet_type_id") == pet]
        for s in bookable:
            ms = s["masters"]
            services.append({
                "id": num(s["id"]), "name": txt(s["name"], 120), "desc": txt(s.get("description"), 600),
                "group": groups.get(s["grooming_service_group_id"], ""),
                "min": min(num(m["min_price"]) for m in ms), "max": max(num(m["max_price"]) for m in ms),
                "dmin": min(num(m["min_duration"]) for m in ms), "dmax": max(num(m["max_duration"]) for m in ms),
            })
        data["services"][key] = services
    reviews = get(f"{API}/reviews")
    reviews = reviews.get("data", reviews) if isinstance(reviews, dict) else reviews
    data["reviews"] = [{
        "name": txt((r.get("creator") or {}).get("firstname") or "Клиент", 40),
        "rating": min(5, max(1, num(r.get("rating") or 5))), "text": txt(r.get("text"), 500) or None,
        "date": txt(r.get("created_at"), 10),
    } for r in reviews]
    return data


def main():
    try:
        data = fetch()
    except Exception as e:  # сеть, формат ответа: сайт соберётся из прошлых данных
        print(f"bimassist недоступен, оставляю прежние данные: {e}", file=sys.stderr)
        return 0
    if not any(data["services"].values()):
        print("bimassist вернул пустой прайс, оставляю прежние данные", file=sys.stderr)
        return 0
    (ROOT / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n = sum(len(v) for v in data["services"].values())
    print(f"Обновлено: {n} услуг, {len(data['employees'])} мастеров, {len(data['reviews'])} отзывов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
