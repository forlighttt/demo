"""Собирает сайт из data.json (данные bimassist) и config.json (ручные настройки) в папку dist/.

Запуск: python build.py
Превью без сервера (ссылки на index.html, запись в новой вкладке): PREVIEW=1 python build.py
"""
import html
import json
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
PREVIEW = os.environ.get("PREVIEW") == "1"
D = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
C = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
ORG = D["org"]
NAME = ORG["name"]
CITY = C.get("city", "Краснодар")
BOOK = C["booking_url"]
assert BOOK.startswith("https://clients.bimassist.ru/"), "booking_url должен вести на clients.bimassist.ru"
BASE = (C.get("base_url") or (f"https://{C['domain']}" if C.get("domain") else "")).rstrip("/")
PH = C.get("photos", {})


def _apply_price_overrides():
    """Правки заказчика поверх прайса из bimassist (config.json → price_overrides)."""
    ov = {k: v for k, v in (C.get("price_overrides") or {}).items() if not k.startswith("_")}
    for key, lst in D["services"].items():
        keep = []
        for sv in lst:
            o = ov.get(str(sv.get("id")), {})
            if o.get("hide"):
                continue
            if "name" in o:
                sv["name"] = str(o["name"])[:120]
            if "desc" in o:
                sv["desc"] = str(o["desc"])[:600]
            if isinstance(o.get("min"), int) and 0 <= o["min"] <= 1_000_000:
                sv["min"] = o["min"]
                if sv.get("max") is not None and sv["max"] < sv["min"]:
                    sv["max"] = sv["min"]
            keep.append(sv)
        D["services"][key] = keep


_apply_price_overrides()
e = html.escape

PAGES = [("", "Главная"), ("gruming-sobak", "Собаки"), ("gruming-koshek", "Кошки"), ("gruming-krolikov", "Кролики"),
         ("mastera", "Мастера"), ("otzyvy", "Отзывы"), ("kontakty", "Контакты")]


# ---------- приведение текстов из bimassist в порядок ----------

def _fix_words(t: str) -> str:
    """Написание, о котором попросил салон: «вычес», а не «вычёс»."""
    return t.replace("вычёс", "вычес").replace("Вычёс", "Вычес")


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"([^\s(])\(", r"\1 (", s)
    s = re.sub(r"(\w)-\s", r"\1 — ", s)
    s = re.sub(r"\s-\s", ": ", s, count=1) if " - " in s and len(s) < 90 else s
    for a, b in (("косметикой — по", "косметикой по"), ("сушка — укладка", "сушка и укладка"),
                 ("косметикой, по типу", "косметикой по типу"), ("длинны", "длины"), ("оконтовка", "окантовка"),
                 ("встречи с Вами", "встрече с вами"), ("Вычес + купание", "Вычес и купание")):
        s = s.replace(a, b)
    return s


def svc_name(s):
    n = tidy(s["name"]).replace("Экспресс линька", "Экспресс-линька").replace("Спа+озон", "Спа + озон")
    return n


def items(desc):
    parts = [p.strip(" ,.") for p in re.split(r"[;.]", tidy(desc))]
    return [p for p in parts if p]


def sentence(desc):
    li = items(desc)
    if not li:
        return ""
    out = [li[0][0].upper() + li[0][1:]] + [x[0].lower() + x[1:] if x[:1].isupper() and not x[1:2].isupper() else x for x in li[1:]]
    return ", ".join(out) + "."


def rub(x):
    return f"{x:,}".replace(",", " ") + " ₽"


def dur(m):
    h, mm = divmod(int(m), 60)
    return " ".join(x for x in (f"{h} ч" if h else "", f"{mm} мин" if mm else ""))


def phone_fmt(p):
    d = re.sub(r"\D", "", p or "")
    return (f"+7 ({d[1:4]}) {d[4:7]}-{d[7:9]}-{d[9:11]}", f"+{d}") if len(d) == 11 else (p, p)


PHONE, PHONE_TEL = phone_fmt(ORG["phone"])
_h = re.findall(r"(\d{1,2}):(\d{2})", ORG["work_time"] or "")
OPEN_FROM, OPEN_TO = ((int(_h[0][0]) * 60 + int(_h[0][1])), (int(_h[1][0]) * 60 + int(_h[1][1]))) if len(_h) >= 2 else (600, 1200)
HM = lambda m: f"{m // 60:02d}:{m % 60:02d}"
HOURS = f"Ежедневно {HM(OPEN_FROM)}–{HM(OPEN_TO)}"
ADDRESS = C.get("address_display") or tidy(ORG["address"])
DOGS = D["services"].get("dogs", [])
CATS = D["services"].get("cats", [])
RABBITS = D["services"].get("rabbits", [])
PRICED = lambda lst: [s for s in lst if s.get("min") is not None]
EXTRA_G = "Дополнительные услуги"
MAIN = lambda lst: [s for s in lst if s["group"] != EXTRA_G]
EXTRA = lambda lst: [s for s in lst if s["group"] == EXTRA_G]
TEXT_REVIEWS = [r for r in D["reviews"] if r.get("text")]
MONTHS = "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()
RATING = f"{float(ORG['rating']):.1f}".replace(".", ",")
ARR = '<span class="arr" aria-hidden="true">→</span>'


ALLOWED_IMG_HOSTS = ("bim-business.hb.bizmrg.com", "business.bimassist.ru")


def safe_url(u, hosts=None):
    """Пропускает только https-ссылки (и, если задано, только с разрешённых доменов). Остальное отбрасывает."""
    from urllib.parse import urlparse
    try:
        p = urlparse(str(u or "").strip())
    except Exception:
        return ""
    if p.scheme != "https" or not p.netloc:
        return ""
    if hosts and p.hostname not in hosts:
        return ""
    return p.geturl()


def rdate(d):
    try:
        y, m, dd = d.split("-")
        return f"{int(dd)} {MONTHS[int(m) - 1]} {y}"
    except Exception:
        return d


def min_price(lst):
    return min((s["min"] for s in lst if s.get("min") is not None), default=0)


def img(r, key, alt, cls="", eager=False):
    src = PH.get(key)
    if not src:
        return ""
    src = src if src.startswith("http") else r + src
    return f'<img src="{e(src)}" alt="{e(alt)}"{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}{"" if eager else " loading=" + chr(34) + "lazy" + chr(34)} decoding="async">'


def lines(*parts):
    return "".join(f'<span class="ln"><span>{p}</span></span>' for p in parts)


# ---------- общие куски ----------

PAW = ('<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><ellipse cx="6" cy="9" rx="2.2" ry="2.8"/>'
       '<ellipse cx="10.3" cy="5.5" rx="2.2" ry="2.8"/><ellipse cx="14.7" cy="5.5" rx="2.2" ry="2.8"/>'
       '<ellipse cx="18.8" cy="9" rx="2.2" ry="2.8"/><path d="M12 11c-3.4 0-6.5 4.2-6.5 6.8 0 2 1.6 2.7 3.2 2.7 1.4 0 2.2-.8 '
       '3.3-.8s1.9.8 3.3.8c1.6 0 3.2-.7 3.2-2.7C18.5 15.2 15.4 11 12 11z"/></svg>')


def book(label="Записаться", service="", cls="btn"):
    return f'<a class="{cls}" href="{e(BOOK)}" target="_blank" rel="noopener" data-book="{e(service)}">{label} {ARR}</a>'


LOGO = C.get("logo") or {}


def logo_mark(r=""):
    if LOGO.get("dark"):
        return f'<img class="logo-img" src="{r}{LOGO["dark"]}" alt="" width="44" height="43">'
    if safe_url(ORG.get("logo"), ALLOWED_IMG_HOSTS):
        return f'<span class="logo-mark"><img src="{e(safe_url(ORG["logo"], ALLOWED_IMG_HOSTS))}" alt="" width="36" height="36"></span>'
    return f'<span class="logo-mark">{PAW}</span>'


def header(r, slug):
    links = "".join(f'<a href="{r}{s}/"{" aria-current=" + chr(34) + "page" + chr(34) if s == slug else ""}>{t}</a>' for s, t in PAGES if s)
    return f'''<header class="site-header">
  <div class="wrap">
    <a class="logo" href="{r or "./"}" aria-label="{e(NAME)}, на главную">{logo_mark(r)}<span>{e(NAME)}</span></a>
    <nav class="nav" id="site-nav" aria-label="Разделы">{links}</nav>
    <div class="head-right">
      <a class="head-phone" href="tel:{PHONE_TEL}">{PHONE}</a>
      {book("Записаться", "", "btn small")}
      <button class="menu-btn" aria-controls="site-nav" aria-expanded="false" aria-label="Меню">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 8h18M3 16h18"/></svg>
      </button>
    </div>
  </div>
</header>'''


def footer(r):
    links = "".join(f'<a href="{r}{s + "/" if s else ""}">{t}</a>' for s, t in PAGES)
    credit = C.get("photo_credit", "")
    return f'''<footer class="site-footer">
  <div class="wrap">
    <div style="display:flex;flex-direction:column;gap:6px">
      {f'<img src="{r}{LOGO["light_sm"]}" alt="{e(NAME)}" width="56" height="54" style="margin-bottom:8px">' if LOGO.get("light_sm") else ""}
      <b>{e(NAME)}</b>
      <span>Груминг-салон · г. {e(CITY)}, {e(ADDRESS)}</span>
      <span><a href="tel:{PHONE_TEL}">{PHONE}</a> · {HOURS}</span>
      {f"<small>{e(credit)}</small>" if credit else ""}
    </div>
    <nav aria-label="Разделы сайта">{links}</nav>
  </div>
</footer>
<div class="sticky-cta">{book("Записаться онлайн")}<a class="btn line" href="tel:{PHONE_TEL}">Позвонить</a></div>
<div class="booking" id="booking" role="dialog" aria-modal="true" aria-label="Онлайн-запись" hidden>
  <div class="booking-box">
    <div class="booking-bar">
      <b data-service-label>Онлайн-запись</b>
      <div class="tools"><a href="{e(BOOK)}" target="_blank" rel="noopener">В новой вкладке</a><button class="booking-close" aria-label="Закрыть">×</button></div>
    </div>
    <iframe title="Онлайн-запись {e(NAME)}" loading="lazy" referrerpolicy="strict-origin-when-cross-origin"
      sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"></iframe>
  </div>
</div>'''


def sec(inner, sid="", head=None, cls=""):
    h = ""
    if head:
        label, h2, p = (tuple(head) + (None,))[:3]
        h = (f'<div class="sec-head rv"><span class="label">{label}</span><h2>{h2}</h2>'
             f'{f"<p>{p}</p>" if p else ""}</div>')
    return f'<section{f" id={chr(34)}{sid}{chr(34)}" if sid else ""}{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}><div class="wrap">{h}{inner}</div></section>'


def ticker():
    names = [svc_name(s) for s in DOGS + CATS]
    seen, uniq = set(), []
    for n in names:
        k = n.split(":")[-1].strip()
        if k.lower() not in seen:
            seen.add(k.lower())
            uniq.append(k[0].upper() + k[1:])
    row = "".join(f"<span>{e(n)}</span><span class=\"sep\">✦</span>" for n in uniq)
    return f'<div class="ticker" aria-hidden="true"><div class="ticker-track">{row}{row}</div></div>'


def row(s):
    if s.get("phone_only"):
        return f'''<a class="row" href="tel:{PHONE_TEL}">
  <div style="display:flex;flex-direction:column;gap:8px;min-width:0">
    <div class="row-title"><h3>{e(svc_name(s))}</h3><span class="fill"></span></div>
    <p class="row-desc">{e(sentence(s["desc"]))}</p>
  </div>
  <div class="row-right" style="display:flex;flex-direction:column;gap:10px;align-items:flex-end">
    <div class="row-price">по телефону</div>
    <div class="row-side"><span class="row-book">Позвонить {ARR}</span></div>
  </div>
</a>'''
    rng = f"от {rub(s['min'])}"
    d = dur(s["dmin"]) if s["dmin"] == s["dmax"] else f"от {dur(s['dmin'])}"
    return f'''<a class="row" href="{e(BOOK)}" target="_blank" rel="noopener" data-book="{e(svc_name(s))}">
  <div style="display:flex;flex-direction:column;gap:8px;min-width:0">
    <div class="row-title"><h3>{e(svc_name(s))}</h3><span class="fill"></span></div>
    <p class="row-desc">{e(sentence(s["desc"]))}</p>
  </div>
  <div class="row-right" style="display:flex;flex-direction:column;gap:10px;align-items:flex-end">
    <div class="row-price">{rng}</div>
    <div class="row-side"><span>{d}</span><span class="row-book">Записаться {ARR}</span></div>
  </div>
</a>'''


def menu(lst):
    out = "".join(row(s) for s in MAIN(lst))
    if EXTRA(lst):
        out += f'<div class="menu-group">Дополнительно к уходу</div>' + "".join(row(s) for s in EXTRA(lst))
    return f'<div class="menu">{out}</div>'


MENU_NOTE = ('<p class="menu-note">Цена зависит от породы и веса питомца. Точную сумму покажет онлайн-запись, '
             'когда вы их укажете. Прайс на сайте обновляется автоматически из системы записи салона.</p>')


RAB_NOTE = ('<p class="menu-note">Кроликов записываем по телефону: мастер уточнит породу, длину шерсти и назовёт цену.</p>')


def price_tabs():
    return f'''<div class="tabs rv" role="tablist" aria-label="Прайс">
  <button role="tab" id="t-dogs" aria-controls="p-dogs" aria-selected="true">Собаки</button>
  <button role="tab" id="t-cats" aria-controls="p-cats" aria-selected="false">Кошки</button>
  {'<button role="tab" id="t-rab" aria-controls="p-rab" aria-selected="false">Кролики</button>' if RABBITS else ""}
</div>
<div id="p-dogs" role="tabpanel" aria-labelledby="t-dogs">{menu(DOGS)}{MENU_NOTE}</div>
<div id="p-cats" role="tabpanel" aria-labelledby="t-cats" hidden>{menu(CATS)}{MENU_NOTE}</div>
{f'<div id="p-rab" role="tabpanel" aria-labelledby="t-rab" hidden>{menu(RABBITS)}{RAB_NOTE}</div>' if RABBITS else ""}'''


def steps():
    st = [("Укажите питомца", "Вид, породу и вес. Система сразу посчитает точную цену."),
          ("Выберите услугу и мастера", "Можно записаться к конкретному грумеру."),
          ("Выберите время", "Свободные окна видны сразу, без звонков и ожидания.")]
    return '<div class="steps">' + "".join(
        f'<div class="step rv rv-d{i}"><span class="n">0{i + 1}</span><h3>{a}</h3><p>{b}</p></div>' for i, (a, b) in enumerate(st)) + "</div>"


def _team():
    """Мастера: сначала из config.json (team.list), затем остальные из bimassist."""
    own = [m for m in (C.get("team") or {}).get("list", []) if m.get("name")]
    names = {m["name"].strip().lower() for m in own}
    return own + [m for m in D["employees"] if m["name"].strip().lower() not in names]


TEAM = _team()


def team(full=False, r=""):
    cards = []
    for i, m in enumerate(TEAM):
        raw = m.get("photo") or ""
        photo = (r + raw) if raw.startswith("assets/") else safe_url(raw, ALLOWED_IMG_HOSTS)
        ph = (f'<img src="{e(photo)}" alt="{e(m["name"])}, {e(m["role"].lower())}" loading="lazy" '
              f'data-fallback="{e(m["name"][:1])}">' if photo
              else f'<span class="initial">{e(m["name"][:1])}</span>')
        cards.append(f'''<article class="master rv rv-d{i % 2}">
  <div class="master-photo">{ph}</div>
  <div class="master-info"><div><span class="label">{e(m["role"])}</span><h3>{e(m["name"])}</h3><p>{e(tidy(m["about"]))}</p></div>
  {book("Записаться", m["name"], "btn line small") if full and m.get("book", True) else ""}</div>
</article>''')
    return f'<div class="team">{"".join(cards)}</div>'


def works(r, kinds, limit=None):
    """Галерея «Наши работы» из реальных фото салона."""
    W = C.get("works") or {}
    items = [p for k in kinds for p in W.get(k, []) if isinstance(p, str) and p.startswith("assets/")]
    if limit:
        items = items[:limit]
    if not items:
        return ""
    cells = "".join(
        f'<a class="work rv rv-d{i % 3}" href="{e(r + p)}.jpg" data-lightbox><img src="{e(r + p)}-s.jpg" alt="Работа салона {e(NAME)}" loading="lazy" decoding="async"></a>'
        for i, p in enumerate(items))
    return f'<div class="works">{cells}</div>'


def before_after():
    pairs = PH.get("before_after") or []
    if not pairs:
        return ""
    p = pairs[0]
    return sec(f'''<div class="ba rv"><img src="{e(p["before"])}" alt="До стрижки" loading="lazy"><img class="after" src="{e(p["after"])}" alt="После стрижки" loading="lazy">
<span class="ba-tag l">До</span><span class="ba-tag r">После</span><span class="ba-handle"></span>
<input type="range" min="0" max="100" value="50" aria-label="Сравнить до и после"></div>''', "works", ("Наши работы", "До и после", "Потяните ползунок."))


FAQ_COMMON = [
    ("Сколько стоит груминг?", f"Цена зависит от вида питомца, породы и веса. Для собак уход стоит от {rub(min_price(MAIN(DOGS)))}, "
     f"для кошек от {rub(min_price(CATS))}. Точную сумму покажет онлайн-запись, когда вы укажете породу и вес."),
    ("Как подготовить питомца к визиту?", "Погуляйте с собакой перед стрижкой и не кормите питомца плотно за 2–3 часа до визита. "
     "Если он волнуется или есть особенности здоровья, напишите об этом в комментарии к записи."),
    ("Вы работаете с кроликами?", "Да. Для кроликов есть экспресс-линька: вычес и купание. Запись и цена по телефону."),
    ("Можно ли выбрать мастера?", "Да. В онлайн-записи можно выбрать любого из наших грумеров и удобное время."),
    ("Когда вы работаете?", f"Каждый день с {HM(OPEN_FROM)} до {HM(OPEN_TO)}, без выходных."),
]


def faq(qs):
    return '<div class="faq rv">' + "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in qs) + "</div>"


def contacts(r=""):
    s = C.get("socials") or {}
    names = {"whatsapp": "WhatsApp", "telegram": "Telegram", "vk": "ВКонтакте"}
    soc = " · ".join(f'<a href="{e(safe_url(u))}" target="_blank" rel="noopener">{names[k]}</a>' for k, u in s.items() if safe_url(u) and k in names)
    mark = f'<img class="contact-logo" src="{r}{LOGO["light"]}" alt="" aria-hidden="true">' if LOGO.get("light") else ""
    return sec(f'''{mark}<div class="rv"><span class="label">Запись по телефону</span></div>
<a class="contact-big rv" href="tel:{PHONE_TEL}">{PHONE}</a>
<div class="contact-grid rv">
  <div><span class="label">Адрес</span><span class="v">г. {e(CITY)}, {e(ADDRESS)}<br><a href="{e(safe_url(C["map_url"]))}" target="_blank" rel="noopener">Открыть в Яндекс.Картах</a></span></div>
  <div><span class="label">Режим работы</span><span class="v">{HOURS}<br><span class="status" data-open-from="{OPEN_FROM}" data-open-to="{OPEN_TO}"><span class="dot"></span><span data-open-text>без выходных</span></span></span></div>
  <div><span class="label">{"Мессенджеры" if soc else "Онлайн-запись"}</span><span class="v">{soc or "Круглосуточно, без звонка"}</span></div>
</div>
<div class="cta-row rv">{book("Записаться онлайн", "", "btn light")}</div>''', "contacts", cls="dark")


def schema():
    offers = [{"@type": "Offer", "name": svc_name(s),
               "priceSpecification": {"@type": "PriceSpecification", "minPrice": s["min"], "maxPrice": s["max"], "priceCurrency": "RUB"}}
              for s in PRICED(DOGS + CATS)]
    d = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": NAME,
         "description": f"Груминг-салон в {CITY}е: стрижка и уход для собак и кошек", "telephone": PHONE_TEL, "image": (BASE + "/" + LOGO["dark"]) if (BASE and LOGO.get("dark")) else safe_url(ORG.get("logo"), ALLOWED_IMG_HOSTS),
         "address": {"@type": "PostalAddress", "streetAddress": ADDRESS, "addressLocality": CITY, "addressCountry": "RU"},
         "openingHours": f"Mo-Su {HM(OPEN_FROM)}-{HM(OPEN_TO)}",
         "priceRange": f"{min(s['min'] for s in PRICED(DOGS + CATS))}–{max(s['max'] for s in PRICED(DOGS + CATS))} ₽",
         "aggregateRating": {"@type": "AggregateRating", "ratingValue": ORG["rating"], "reviewCount": ORG["review_count"]},
         "hasOfferCatalog": {"@type": "OfferCatalog", "name": "Услуги груминга", "itemListElement": offers}}
    if BASE:
        d["url"] = BASE + "/"
    # < > & заменяем на \uXXXX, чтобы текст из bimassist не смог закрыть тег <script> разметки
    return json.dumps(d, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def metrika_noscript():
    mid = str(C.get("yandex_metrika_id") or "").strip()
    if not mid.isdigit():
        return ""
    return f'<noscript><div><img src="https://mc.yandex.ru/watch/{mid}" style="position:absolute;left:-9999px" alt=""></div></noscript>'


def csp():
    """Политика безопасности контента: браузер выполнит только наши скрипты и загрузит ресурсы только с перечисленных доменов."""
    return "; ".join([
        "default-src 'self'",
        "script-src 'self' https://mc.yandex.ru https://yastatic.net",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: https://bim-business.hb.bizmrg.com https://business.bimassist.ru https://mc.yandex.ru https://mc.yandex.com",
        "connect-src 'self' https://mc.yandex.ru https://mc.yandex.com wss://mc.yandex.ru",
        "frame-src https://clients.bimassist.ru https://mc.yandex.ru https://mc.yandex.com",
        "child-src https://clients.bimassist.ru https://mc.yandex.ru https://mc.yandex.com",
        "object-src 'none'", "base-uri 'self'", "form-action 'none'", "upgrade-insecure-requests",
    ])


def page(slug, title, desc, body):
    r = "../" if slug else ""
    canon = f'<link rel="canonical" href="{BASE}/{slug + "/" if slug else ""}">' if BASE else ""
    og = PH.get("hero")
    og_img = f'<meta property="og:image" content="{e(og if og.startswith("http") or not BASE else BASE + "/" + og)}">' if og else ""
    mid = str(C.get("yandex_metrika_id") or "").strip()
    return f'''<!doctype html>
<html lang="ru" class="js">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="Content-Security-Policy" content="{csp()}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<meta http-equiv="X-Content-Type-Options" content="nosniff">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
{canon}
<meta property="og:type" content="website">
<meta property="og:locale" content="ru_RU">
<meta property="og:site_name" content="{e(NAME)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
{og_img}
<meta name="theme-color" content="#0D0D0D">
<link rel="icon" href="{r}assets/favicon.png" type="image/png">
<link rel="apple-touch-icon" href="{r}assets/favicon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap">
<link rel="stylesheet" href="{r}assets/style.css">
<script type="application/ld+json">{schema()}</script>
<noscript><style>.js .rv,.js .ln>span,.js .hero-photo img{{opacity:1!important;transform:none!important}}</style></noscript>
</head>
<body data-booking="{e(safe_url(BOOK))}" data-metrika="{e(mid if mid.isdigit() else "")}">
{metrika_noscript()}
{header(r, slug)}
<main>
{body}
</main>
{footer(r)}
<script src="{r}assets/app.js" defer></script>
</body>
</html>
'''


def page_hero(r, crumb, h1_lines, lead, photo_key=None, photo_alt="", phone_first=False):
    photo = img(r, photo_key, photo_alt, "ph-img", eager=True) if photo_key else ""
    return f'''<section class="page-hero dark">{photo}<div class="wrap">
<div class="crumbs"><a href="../">Главная</a> / {crumb}</div>
<h1>{lines(*h1_lines)}</h1><p class="lead">{lead}</p>
<div class="cta-row">{f'<a class="btn light" href="tel:{PHONE_TEL}">Позвонить {PHONE}</a>' if phone_first else book("Записаться онлайн", "", "btn light") + f'<a class="btn line" href="tel:{PHONE_TEL}">{PHONE}</a>'}</div>
</div></section>'''


# ---------- страницы ----------

def home():
    r = ""
    body = f'''<section class="hero dark"><div class="wrap">
  <div class="hero-grid">
    <div class="hero-text">
      <span class="label">Груминг-салон · {e(CITY)}</span>
      <h1>{lines("Груминг", "<em>по породе</em>", f"в {e(CITY)}е")}</h1>
      <p class="hero-lead">Стрижём собак и кошек, помогаем кроликам пережить линьку. Всё так, как требует их порода и шерсть: профессиональная косметика, модельные и гигиенические стрижки, экспресс-линька, чистка зубов ультразвуком.</p>
      <div class="cta-row" style="margin-top:0">{book("Записаться онлайн", "", "btn light")}<a class="btn line" href="#prices">Цены</a></div>
    </div>
    <div class="hero-photo">{img(r, "hero", "Ухоженная собака после груминга", eager=True)}</div>
  </div>
  <div class="hero-meta">
    <div><span class="label">Рейтинг</span><b><span class="stars" aria-hidden="true">★</span> {RATING}</b><a href="otzyvy/" class="label" style="text-transform:none;letter-spacing:0">{ORG["review_count"]} отзывов</a></div>
    <div><span class="label">Сегодня</span><b class="status" data-open-from="{OPEN_FROM}" data-open-to="{OPEN_TO}"><span class="dot"></span><span data-open-text>{HM(OPEN_FROM)}–{HM(OPEN_TO)}</span></b><span class="label" style="text-transform:none;letter-spacing:0">без выходных</span></div>
    <div><span class="label">Адрес</span><b>{e(ADDRESS)}</b><a href="{e(safe_url(C["map_url"]))}" target="_blank" rel="noopener" class="label" style="text-transform:none;letter-spacing:0">Открыть на карте →</a></div>
  </div>
</div></section>
{ticker()}'''
    pets = f'''<div class="pets">
  <a class="pet rv" href="gruming-sobak/">{img(r, "dogs", "Собака на груминге")}<div class="pet-body"><div><h3>Собаки</h3><span class="from">{len(DOGS)} услуг · от {rub(min_price(MAIN(DOGS)))}</span></div><span class="circle" aria-hidden="true">→</span></div></a>
  <a class="pet rv rv-d1" href="gruming-koshek/">{img(r, "cats", "Кошка на груминге")}<div class="pet-body"><div><h3>Кошки</h3><span class="from">{len(CATS)} услуги · от {rub(min_price(CATS))}</span></div><span class="circle" aria-hidden="true">→</span></div></a>
  {f'<a class="pet rv rv-d2" href="gruming-krolikov/">{img(r, "rabbits", "Кролик на груминге")}<div class="pet-body"><div><h3>Кролики</h3><span class="from">линька · запись по телефону</span></div><span class="circle" aria-hidden="true">→</span></div></a>' if RABBITS else ""}
</div>'''
    body += sec(pets, "", ("Для кого", "Собаки, кошки и кролики" if RABBITS else "Собаки и кошки", "Своя программа ухода для каждого вида: с купанием и без, стрижка под машинку или модельная, вычес во время линьки."))
    body += sec(price_tabs(), "prices", ("Прайс", "Услуги и цены", "Нажмите на услугу, чтобы сразу записаться."))
    g = works(r, ["home"])
    if g:
        body += sec(g + f'<div class="cta-row rv"><a class="btn line" href="gruming-sobak/#works">Работы с собаками {ARR}</a><a class="btn line" href="gruming-koshek/#works">Работы с кошками {ARR}</a></div>',
                    "works", ("Наши работы", "Питомцы после груминга", "Реальные фото питомцев после груминга в нашем салоне."))
    body += sec(team(r=r) + f'<div class="cta-row rv"><a class="btn line" href="mastera/">Подробнее о мастерах {ARR}</a></div>', "team", ("Мастера", "Кто будет стричь"), cls="dark")
    body += before_after()
    body += sec(steps() + f'<div class="cta-row rv">{book("Перейти к записи")}</div>', "how", ("Онлайн-запись", "Три шага до записи"))
    quote = TEXT_REVIEWS[0]["text"] if TEXT_REVIEWS else "Все супер!"
    body += sec(f'''<p class="quote rv">«{e(quote.rstrip("!"))}<em>!</em>»</p>
<div class="quote-by rv"><span class="stars" aria-hidden="true">★★★★★</span><span>{e(TEXT_REVIEWS[0]["name"]) if TEXT_REVIEWS else ""}, отзыв в системе записи</span></div>
<div class="revs rv">
  <div><b>{RATING}</b><span>средняя оценка</span></div>
  <div><b>{ORG["review_count"]}</b><span>отзывов, все на пять звёзд</span></div>
  <div><b>{len(TEAM)}</b><span>мастера в команде</span></div>
</div>
<div class="cta-row rv"><a class="btn line" href="otzyvy/">Все отзывы {ARR}</a></div>''', "reviews", cls="dark")
    body += sec(faq(FAQ_COMMON), "faq", ("Вопросы", "Частые вопросы"))
    body += contacts("")
    return page("", f"{NAME}: груминг-салон в {CITY}е для собак и кошек",
                f"Груминг собак и кошек в {CITY}е, {ADDRESS}. Стрижка по породе, экспресс-линька, чистка зубов. Цены от {rub(min_price(DOGS + CATS))}. Онлайн-запись, {HOURS.lower()}.", body)


def pet_page(slug, lst, h1_lines, crumb, lead, faq_extra, title, desc, photo_key, photo_alt, kind="dogs"):
    r = "../"
    body = page_hero(r, crumb, h1_lines, lead, photo_key, photo_alt)
    body += ticker()
    body += sec(menu(lst) + MENU_NOTE, "prices", ("Прайс", "Услуги и цены", "Нажмите на услугу, чтобы сразу записаться."))
    g = works(r, [kind])
    if g:
        body += sec(g, "works", ("Наши работы", "Питомцы после груминга", "Реальные фото из салона."))
    body += sec(team(r=r), "", ("Мастера", "Кто будет ухаживать"), cls="dark")
    body += sec(steps(), "how", ("Онлайн-запись", "Три шага до записи"))
    body += sec(faq(faq_extra + FAQ_COMMON[1:]), "faq", ("Вопросы", "Частые вопросы"))
    body += contacts("../")
    return page(slug, title, desc, body)


def find(lst, *words):
    return next((s for s in lst if all(w in s["name"].lower() for w in words)), None)


def dogs_page():
    hyg, model = find(DOGS, "гигиен"), find(DOGS, "модельн")
    qs = []
    if hyg and model:
        qs.append(("Сколько стоит стрижка собаки?", f"Гигиенический уход стоит от {rub(hyg['min'])}, модельная стрижка от {rub(model['min'])}. "
                   "Точная цена зависит от породы и веса, онлайн-запись покажет её сразу."))
        qs.append(("Сколько длится стрижка?", f"Гигиенический уход занимает от {dur(hyg['dmin'])}, модельная стрижка от {dur(model['dmin'])}. "
                   "Крупным и длинношёрстным собакам нужно больше времени."))
    return pet_page("gruming-sobak", DOGS, ("Груминг", "<em>собак</em>"), "Собаки",
                    f"Модельные и гигиенические стрижки, стрижка под машинку с оформлением головы, экспресс-линька, ультразвуковая чистка зубов. {e(CITY)}, {e(ADDRESS)}.",
                    qs, f"Груминг собак в {CITY}е: стрижка и цены | {NAME}",
                    f"Стрижка собак в {CITY}е: модельная, гигиеническая, под машинку, экспресс-линька, чистка зубов. Цены от {rub(min_price(DOGS))}. Онлайн-запись.",
                    "dogs_page", "Собака после груминга")


def cats_page():
    cut, comb = find(CATS, "без купания", "стрижк"), find(CATS, "вычес")
    qs = []
    if cut and comb:
        qs.append(("Сколько стоит стрижка кошки?", f"Стрижка без купания стоит от {rub(cut['min'])}, вычес без купания от {rub(comb['min'])}. Точную цену покажет онлайн-запись."))
    qs.append(("Можно ли без купания?", "Да, есть стрижка без купания и вычес без купания. Это удобно для кошек, которые плохо переносят воду."))
    return pet_page("gruming-koshek", CATS, ("Груминг", "<em>кошек</em>"), "Кошки",
                    f"Стрижка и бритьё с купанием и без, экспресс-линька, вычес линялой шерсти. {e(CITY)}, {e(ADDRESS)}.",
                    qs, f"Груминг кошек в {CITY}е: стрижка и вычес | {NAME}",
                    f"Стрижка и вычес кошек в {CITY}е, с купанием и без. Экспресс-линька. Цены от {rub(min_price(CATS))}. Онлайн-запись.",
                    "cats_page", "Кошка после груминга", kind="cats")


def rabbits_page():
    r = "../"
    body = page_hero(r, "Кролики", ("Груминг", "<em>кроликов</em>"),
                     f"Экспресс-линька для кроликов: бережный вычес и купание. {e(CITY)}, {e(ADDRESS)}. Запись по телефону.",
                     "rabbits_page", "Кролик после груминга", phone_first=True)
    body += sec(menu(RABBITS) + RAB_NOTE + f'<div class="cta-row rv"><a class="btn" href="tel:{PHONE_TEL}">Позвонить {PHONE}</a></div>',
                "prices", ("Прайс", "Услуги для кроликов"))
    body += sec(faq([("Зачем кролику груминг?", "Во время линьки кролики глотают шерсть, когда вылизываются. Вычес убирает лишнюю шерсть и помогает пережить линьку легче."),
                     ("Сколько стоит?", "Цена зависит от породы и длины шерсти. Позвоните, мастер уточнит детали и назовёт стоимость.")] + FAQ_COMMON[3:]),
                "faq", ("Вопросы", "Частые вопросы"))
    body += contacts("../")
    return page("gruming-krolikov", f"Груминг кроликов в {CITY}е: вычес и линька | {NAME}",
                f"Груминг кроликов в {CITY}е: экспресс-линька, вычес и купание. {ADDRESS}. Запись по телефону {PHONE}.", body)


def masters_page():
    body = page_hero("../", "Мастера", ("Наши", "<em>грумеры</em>"), "Записаться можно к конкретному мастеру: выберите его в онлайн-записи.")
    body += sec(team(full=True, r="../"), cls="dark")
    body += contacts("../")
    return page("mastera", f"Грумеры салона {NAME} в {CITY}е", f"Мастера груминг-салона {NAME}: опыт, специализация, запись к мастеру онлайн.", body)


def reviews_page():
    cards = "".join(f'''<div class="rv"><span class="stars" aria-label="{r["rating"]} из 5">{"★" * int(r["rating"] or 5)}</span>
{f"<p>{e(r['text'])}</p>" if r.get("text") else "<p class='muted'>Оценка без текста</p>"}<span class="who">{e(r["name"])} · {rdate(r["date"])}</span></div>''' for r in D["reviews"])
    body = page_hero("../", "Отзывы", (f"{RATING} из 5", f"<em>{ORG['review_count']} отзывов</em>"), "Отзывы оставляют клиенты после визита, в системе онлайн-записи салона.")
    body += sec(f'<div class="rev-list">{cards}</div>')
    body += contacts("../")
    return page("otzyvy", f"Отзывы о груминг-салоне {NAME}, {CITY}", f"Отзывы клиентов груминг-салона {NAME}: средняя оценка {RATING}, {ORG['review_count']} отзывов.", body)


def contacts_page():
    body = page_hero("../", "Контакты", ("Как нас", "<em>найти</em>"), f"г. {e(CITY)}, {e(ADDRESS)}. {HOURS}, без выходных.")
    body += contacts("../")
    return page("kontakty", f"Контакты груминг-салона {NAME}, {CITY}", f"Адрес, телефон и режим работы груминг-салона {NAME}: г. {CITY}, {ADDRESS}, {HOURS.lower()}.", body)


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ROOT / "assets", DIST / "assets")
    pages = {"": home(), "gruming-sobak": dogs_page(), "gruming-koshek": cats_page(), **({"gruming-krolikov": rabbits_page()} if RABBITS else {}),
             "mastera": masters_page(), "otzyvy": reviews_page(), "kontakty": contacts_page()}
    for slug, content in pages.items():
        p = DIST / slug / "index.html" if slug else DIST / "index.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        if PREVIEW:
            slugs = "|".join(x for x in pages if x)
            content = re.sub(rf'href="((?:\.\./)?)({slugs})/"', r'href="\1\2/index.html"', content)
            content = content.replace('href="../"', 'href="../index.html"').replace('href="./"', 'href="index.html"')
            content = re.sub(r' data-book="[^"]*"', "", content)
        p.write_text(_fix_words(content), encoding="utf-8")
    nf = page("", f"Страница не найдена | {NAME}", "Страница не найдена",
              f'<section class="page-hero dark"><div class="wrap"><h1>{lines("404")}</h1><p class="lead">Такой страницы нет. Возможно, ссылка устарела.</p>'
              f'<div class="cta-row"><a class="btn light" href="/">На главную {ARR}</a>{book("Записаться", "", "btn line")}</div></div></section>')
    nf = re.sub(r'(href|src)="(assets/)', r'\1="/\2', nf)
    (DIST / "404.html").write_text(nf, encoding="utf-8")
    (DIST / "robots.txt").write_text("User-agent: *\nAllow: /\n" + (f"Sitemap: {BASE}/sitemap.xml\n" if BASE else ""), encoding="utf-8")
    if BASE:
        urls = "".join(f"<url><loc>{BASE}/{s + '/' if s else ''}</loc></url>" for s in pages)
        (DIST / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', encoding="utf-8")
    if C.get("domain"):
        (DIST / "CNAME").write_text(C["domain"] + "\n", encoding="utf-8")
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Собрано {len(pages)} страниц в {DIST}")


if __name__ == "__main__":
    main()
