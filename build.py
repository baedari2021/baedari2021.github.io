#!/usr/bin/env python3
"""배다리마을관리 사회적협동조합 홈페이지 빌드 스크립트.

사용법:  python3 build.py            # 블로그 RSS를 읽어 dist/ 를 새로 만듭니다
         python3 build.py --offline  # 인터넷 없이 마지막으로 저장한 소식(data/news.json)으로 빌드

dist/ 폴더를 그대로 Cloudflare Pages / GitHub Pages 등에 올리면 됩니다.
"""
import html, json, os, re, shutil, sys, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).parent
DATA, STATIC, DIST = ROOT / "data", ROOT / "static", ROOT / "dist"
E = html.escape


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


SITE = load("site.json")
PEOPLE = load("people.json")
TIMELINE = load("timeline.json")
PARTNERS = load("partners.json")
WORK = load("work.json")
OPEN = load("open.json")
CARE = load("care.json")
WARN = []
# 임원: 파일 형식(이사장·이사·감사)을 목록으로 바꿔 관리페이지 자료와 같은 모양으로 씁니다
OFFICERS = ([{"role": "이사장", "name": PEOPLE["chair"]["name"]}] + [{"role": "이사", "name": n} for n in PEOPLE["directors"]]
            + [{"role": "감사", "name": PEOPLE["auditor"]["name"]}])


def web_url(u, https_only=False):
    """바깥에서 온 주소는 http(s) 로 시작할 때만 씁니다."""
    u = str(u or "")
    return u if u.startswith(("https://",) if https_only else ("https://", "http://")) else ""


def apply_content(ex):
    """관리페이지의 홈페이지 내용(기본정보·임원·연혁·하는 일·통합돌봄)을 파일 내용 위에 덮어씁니다."""
    if "officers" in ex:
        OFFICERS[:] = ex["officers"]
    if "history" in ex:
        TIMELINE[:] = ex["history"]
    if "areas" in ex:
        WORK["areas"] = [dict(a, id="gift" if a.get("link") else f"area{i}") for i, a in enumerate(ex["areas"], 1)]
    site = ex.get("site")
    if site:
        for k in ("tagline", "intro", "founded", "address", "phone", "email", "donation_guide"):
            if k in site:
                SITE[k] = str(site[k])
        SITE["members"] = int(site.get("members") or SITE["members"])
        SITE["shop_url"] = web_url(site.get("shop_url"), True) or SITE["shop_url"]
        SITE["sns"] = {k: web_url(v, True) for k, v in site.get("sns", {}).items()}
        fc = site.get("first_claim", {})
        SITE["first_claim"].update(source_title=str(fc.get("source_title", "")), source_url=web_url(fc.get("source_url")))
        SITE["donation_open"] = site.get("donation_open") is True
    care = ex.get("care")
    if care:
        CARE.update({k: care[k] for k in ("lead", "short", "why", "returns", "compare", "process", "network", "roadmap") if k in care})


def merge_admin_export():
    """관리페이지에서 공개한 후원금 자료·실적·공고를 가져와 합칩니다(site.json export_url 이 있을 때)."""
    url = SITE.get("export_url")
    if not url or "--offline" in sys.argv:
        return
    try:
        ex = json.loads(urllib.request.urlopen(url + ("&" if "?" in url else "?") + "export=public", timeout=30).read())
    except Exception as ex_:
        if os.environ.get("CI"):   # 자동 배포 중이면 중단해 직전에 게시된 화면을 그대로 둡니다
            sys.exit(f"관리페이지 공개 자료를 읽지 못해 배포를 중단합니다: {ex_}")
        WARN.append(f"관리페이지 공개 자료를 읽지 못했습니다(기존 data 사용): {ex_}")
        return
    for item in ex.get("years", []) + ex.get("notices", []):
        if not str(item.get("file", "")).startswith("https://"):
            item["file"] = ""
    done = {y["year"] for y in ex.get("years", [])}
    OPEN["years"] = sorted(ex.get("years", []) + [y for y in OPEN["years"] if y["year"] not in done],
                           key=lambda y: y["year"], reverse=True)
    if ex.get("records") or (ex.get("v", 1) >= 2 and "records" in ex):
        WORK["records"] = ex["records"]
    if ex.get("notices") or (ex.get("v", 1) >= 2 and "notices" in ex):
        OPEN["notices"] = ex["notices"]
    apply_content(ex)
    # 언론·표창·협약은 관리 시트가 원본: 관리페이지에서 지우거나 비공개로 바꾸면 홈페이지에서도 빠집니다
    for key in ("press", "awards", "mou"):
        if key in ex:
            PARTNERS[key] = ex[key]
    for item in PARTNERS["press"]:
        if not str(item.get("url", "")).startswith(("https://", "http://")):
            item["url"] = ""


merge_admin_export()

# ---------------------------------------------------------------- 블로그 소식
RSS = "https://rss.blog.naver.com/baedaricoop.xml"


def fetch_news():
    cache = DATA / "news.json"
    if "--offline" not in sys.argv:
        try:
            req = urllib.request.Request(RSS, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=30).read()
            items = []
            for it in ET.fromstring(raw).iter("item"):
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").split("?")[0]
                if not link.startswith("https://blog.naver.com/"):
                    continue
                cat = (it.findtext("category") or "").strip()
                date = (it.findtext("pubDate") or "")[5:16]
                desc = re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or ""))
                desc = re.sub(r"\s+", " ", desc).strip()
                items.append({"title": title, "link": link, "category": cat, "date": date, "summary": desc[:110]})
            if items:
                cache.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as ex:  # 네트워크 실패 시 저장해 둔 목록 사용
            WARN.append(f"블로그 RSS를 읽지 못해 저장된 소식을 사용합니다: {ex}")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    WARN.append("소식 목록이 비어 있습니다.")
    return []


MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def ymd(d):
    m = re.match(r"(\d+) (\w+) (\d{4})", d or "")
    return f"{m.group(3)}.{MONTHS[m.group(2)]:02d}.{int(m.group(1)):02d}" if m else (d or "")


NEWS = fetch_news()

# ---------------------------------------------------------------- 공통 요소
NAV = [("about.html", "우리는"), ("work.html", "하는 일"), ("care.html", "통합돌봄"), ("news.html", "소식"),
       ("join.html", "함께하기"), ("open.html", "투명경영")]
SHOP_LABEL = "판촉물은 배다리"   # 공식 슬로건


def utm(url):
    return url + ("&" if "?" in url else "?") + "utm_source=baedari&utm_medium=site"


def ext(url, label, cls=""):
    """새 창으로 열리는 바깥 링크."""
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{E(url)}" target="_blank" rel="noopener noreferrer">{label}</a>'


def shop_link(label, cls="btn"):
    return ext(utm(SITE["shop_url"]), label + '<span class="ico" aria-hidden="true">↗</span><span class="sr"> (새 창)</span>', cls)


def tile(x, y, kind, color, rot=0, s=84):
    cx, cy = x + s / 2, y + s / 2
    if kind == "sq":
        return f'<rect x="{x}" y="{y}" width="{s}" height="{s}" fill="{color}"/>'
    if kind == "ci":
        return f'<circle cx="{cx}" cy="{cy}" r="{s/2}" fill="{color}"/>'
    if kind == "sm":
        return f'<circle cx="{cx}" cy="{cy}" r="{s*0.3}" fill="{color}"/>'
    # quarter circle
    d = f"M{x},{y+s} A{s},{s} 0 0 1 {x+s},{y} L{x+s},{y+s} Z"
    return f'<path d="{d}" fill="{color}" transform="rotate({rot} {cx} {cy})"/>'


def mosaic(cls="mosaic"):
    T, L, P, Y, G, D = "#3f9d93", "#8dd0c6", "#d6f0ea", "#e8b23a", "#b9cc45", "#25695f"
    spec = [("q", T, 0), ("sq", P, 0), ("q", Y, 90), ("ci", L, 0),
            ("sq", L, 0), ("q", D, 180), ("sq", T, 0), ("q", P, 270),
            ("q", G, 90), ("sm", Y, 0), ("q", L, 0), ("sq", D, 0)]
    out = []
    for n, (k, c, r) in enumerate(spec):
        x, y = (n % 4) * 90, (n // 4) * 90
        out.append(tile(x, y, {"q": "q"}.get(k, k), c, r))
    return f'<svg class="{cls}" viewBox="0 0 354 264" role="img" aria-hidden="true" focusable="false">{"".join(out)}</svg>'


def layout(page, title, body, desc=None, base=False):
    desc = desc or SITE["intro"]
    nav = "".join(
        f'<li><a href="{h}"{" aria-current=page" if h == page else ""}>{t}</a></li>' for h, t in NAV)
    sns = "".join(ext(SITE["sns"][k], n) for k, n in [
        ("blog", "네이버 블로그"), ("instagram", "인스타그램"), ("facebook", "페이스북"), ("youtube", "유튜브")] if SITE["sns"].get(k))
    full_title = f'{SITE["name"]} | {SITE["tagline"]}' if page == "index.html" else f'{title} | {SITE["name"]}'
    url = f'{SITE["domain"]}/' + ("" if page == "index.html" else page)
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
{'<base href="/">' if base else ''}
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#3f9d93">
<title>{E(full_title)}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:locale" content="ko_KR">
<meta property="og:site_name" content="{E(SITE['name'])}">
<meta property="og:title" content="{E(full_title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:image" content="{SITE['domain']}/logo.png">
<meta property="og:url" content="{url}">
<link rel="icon" href="logo.png">
<link rel="apple-touch-icon" href="logo.png">
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<link rel="stylesheet" href="style.css">
<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@type": "Organization", "name": SITE["name"], "url": SITE["domain"], "logo": SITE["domain"] + "/logo.png", "address": SITE["address"], "telephone": SITE["phone"], "email": SITE["email"], "sameAs": [u for u in SITE["sns"].values() if u]}, ensure_ascii=False).replace("<", "\\u003c")}</script>
</head>
<body>
<a class="skip" href="#main">본문 바로가기</a>
<header class="site-header">
  <div class="wrap bar">
    <a class="brand" href="index.html" aria-label="{E(SITE['name'])} 홈"><img src="logo.png" alt="" width="44" height="34"><span class="bn">배다리<small>마을관리 사회적협동조합</small></span></a>
    <button class="menu-btn" aria-expanded="false" aria-controls="gnb"><span class="bars" aria-hidden="true"></span><span class="sr">메뉴</span></button>
    <nav id="gnb" aria-label="주 메뉴">
      <ul>{nav}</ul>
      {shop_link(SHOP_LABEL, "shop-cta")}
    </nav>
  </div>
</header>
<main id="main">
{body}
</main>
<footer class="site-footer">
  <div class="wrap fgrid">
    <div class="fbrand"><img src="logo.png" alt="" width="52" height="40"><strong>{E(SITE['name'])}</strong>
      <p>{E(SITE['tagline'])}</p></div>
    <div><h2>연락처</h2><p>{E(SITE['address'])}<br>전화 {E(SITE['phone'])}<br><a href="mailto:{E(SITE['email'])}">{E(SITE['email'])}</a></p></div>
    <div><h2>바로가기</h2><ul>
      <li><a href="open.html#donations">후원금 모집·사용 내역</a></li>
      <li><a href="open.html">정관·공시 자료</a></li>
      <li>{shop_link(SHOP_LABEL, "")}</li></ul></div>
    <div><h2>소식 채널</h2><p class="sns">{sns}</p></div>
  </div>
  <div class="wrap copy"><span>© {E(SITE['name'])}</span><span><a href="privacy.html"><b>개인정보처리방침</b></a> · 사회적협동조합 · 공익법인(구 지정기부금단체)</span></div>
</footer>
<script src="main.js"></script>
</body>
</html>
"""


def page_head(title, lead, crumb):
    return f"""<section class="page-head"><div class="wrap">
<p class="crumb"><a href="index.html">홈</a><span aria-hidden="true">/</span><span>{crumb}</span></p>
<h1>{title}</h1><p class="lead">{lead}</p></div></section>"""


def block(heading, inner, lead="", cls="", sid=""):
    i = f' id="{sid}"' if sid else ""
    l = f'<p class="sub">{lead}</p>' if lead else ""
    return f'<section class="blk {cls}"{i}><div class="wrap"><div class="sec-head"><h2>{heading}</h2>{l}</div>{inner}</div></section>'


def arrow_link(href, label, new=False):
    if new:
        return ext(href, f'{label}<span class="ico" aria-hidden="true">↗</span><span class="sr"> (새 창)</span>', "tlink")
    return f'<a class="tlink" href="{href}">{label}<span class="ico" aria-hidden="true">→</span></a>'


def news_rows(items, n=None):
    out = []
    for it in (items[:n] if n else items):
        out.append(
            f'<li data-cat="{E(it["category"])}"><a href="{E(it["link"])}" target="_blank" rel="noopener noreferrer">'
            f'<time datetime="{ymd(it["date"]).replace(".", "-")}">{ymd(it["date"])}</time>'
            f'<span class="body"><span class="cat">{E(it["category"])}</span><span class="t">{E(it["title"])}</span>'
            + (f'<span class="sum">{E(it["summary"])}…</span>' if n is None and it.get("summary") else "")
            + f'</span><span class="go" aria-hidden="true">↗</span><span class="sr"> (새 창)</span></a></li>')
    return f'<ul class="rows">{"".join(out)}</ul>'


def press_list():
    rows = []
    for p in PARTNERS["press"]:
        t = E(p["title"])
        if p["url"]:
            head = f'<a href="{E(p["url"])}" target="_blank" rel="noopener noreferrer">{t}<span class="sr"> (새 창)</span></a>'
        else:
            head = f'<span>{t}</span>'
            WARN.append(f'언론 기사 URL 없음(링크 미연결): {p["title"]}')
        rows.append(f'<li>{head}<span class="meta">{E(p["outlet"])} · {p["date"]}</span></li>')
    return f'<ul class="plain">{"".join(rows)}</ul>' if rows else '<p class="note">등록된 보도가 없습니다.</p>'


def mou_list():
    if not PARTNERS["mou"]:
        return '<p class="note">등록된 협약이 없습니다.</p>'
    return '<ul class="plain mou">' + "".join(
        f'<li><b>{E(m["name"])}</b><span class="meta">{m["date"]} {E(m.get("kind", "업무협약"))}</span>' + (f'<span class="d">{E(m["desc"])}</span>' if m.get("desc") else "") + '</li>'
        for m in PARTNERS["mou"]) + "</ul>"


def award_block(h="h3"):
    if not PARTNERS["awards"]:
        WARN.append("표창 목록(partners.json awards)이 비어 있어 표창 영역이 표시되지 않습니다.")
        return ""
    rows = "".join(
        f'<li><b>{E(a["title"])}</b><span class="meta">{E(a.get("date", ""))} · {E(a.get("org", ""))}</span>'
        f'<span class="d">{E(a.get("who", ""))}</span></li>' for a in PARTNERS["awards"])
    return f'<{h}>표창</{h}><ul class="plain mou">{rows}</ul>'


# ---------------------------------------------------------------- 페이지
def page_index():
    fc = SITE["first_claim"]
    src = (ext(fc["source_url"], E(fc["source_title"])) if fc["source_url"] else E(fc["source_title"]))
    if not fc["source_url"]:
        WARN.append("'첫 마을관리 사회적협동조합' 출처 URL(site.json first_claim.source_url)이 비어 있습니다.")
    first, comma, last = SITE["tagline"].partition(",")
    if not comma:
        first, last = "", first
    head_part, _, last_word = last.strip().rpartition(" ")
    h1 = (f"{E(first.strip())},<br>" if first else "") + (f"{E(head_part)} " if head_part else "") + f"<em>{E(last_word)}</em>"
    trust = [("사회적협동조합", "2020.11 설립 인가 (국토교통부)"),
             ("공익법인", "구 지정기부금단체 · 기부금영수증 발급"),
             ("경기도·고양시 첫", "마을관리 사회적협동조합")]
    src_line = f'<p class="src">출처: {src}</p>' if fc["source_title"] else ""
    trust_html = "".join(f'<li><span class="mk" aria-hidden="true"></span><b>{a}</b><span>{b}</span></li>' for a, b in trust)
    areas = [a for a in WORK["areas"] if a["id"] != "gift"]
    area_html = "".join(
        f'<li><span class="num">{n:02d}</span><div><h3>{E(a["title"])}</h3><p>{E(a["lead"])}</p></div></li>'
        for n, a in enumerate(areas, 1))
    join_html = "".join(
        f'<li><a href="join.html#{i}"><h3>{t}</h3><p>{d}</p><span class="go" aria-hidden="true">→</span></a></li>'
        for i, t, d in [("member", "조합원 되기", "마을과 함께하고 싶은 분을 기다립니다."),
                        ("donate", "후원하기", "공익법인으로서 후원금 사용 내역을 투명하게 공개합니다."),
                        ("request", "사업 의뢰", "교육·집수리·행사 등 협력 문의를 받습니다.")])
    trust_blk = f"""<section class="blk soft" id="trust"><div class="wrap">
<div class="sec-head"><h2>신뢰 경영</h2><p class="sub">조합의 활동과 운영은 공개된 자료로 확인하실 수 있습니다.</p></div>
<div class="two">
  <div><h3>협력 협약</h3>{mou_list()}{award_block()}</div>
  <div><h3>언론 보도</h3>{press_list()}</div>
</div>
<a class="open-card" href="open.html"><div><b>정관 · 결산 · 후원금 모집·사용 내역</b><span>공익법인으로서 운영 자료를 투명하게 공개합니다.</span></div><span class="go" aria-hidden="true">→</span></a>
</div></section>"""
    steps = "".join(f'<li><b>{E(n)}</b><span>{E(d)}</span></li>' for n, d in CARE["process"])
    care_band = f"""<section class="careband" id="care"><div class="wrap">
<div class="cb-head"><p class="kicker">추진 중인 일</p><h2>살던 곳에서 계속 사는 삶, 통합돌봄(AIP)</h2>
<p>{E(CARE['short'])}</p></div>
<ol class="steps">{steps}</ol>
<p class="more">{arrow_link("care.html", "통합돌봄 추진 계획 보기")}</p></div></section>"""
    body = f"""
<section class="hero"><div class="wrap hgrid">
  <div class="htext">
    <p class="kicker">고양시 원당 · 마을관리 사회적협동조합</p>
    <h1>{h1}</h1>
    <p class="intro">{E(SITE['intro'])}</p>
    <p class="cta"><a class="btn solid" href="join.html">함께하기</a>{shop_link(SHOP_LABEL, "btn ghost")}</p>
    <a class="nowchip" href="care.html"><span class="dot" aria-hidden="true"></span><b>추진 중</b>고양시형 통합돌봄(AIP) 거점<span class="go" aria-hidden="true">→</span></a>
  </div>
  <div class="hart">{mosaic()}</div>
</div></section>
<section class="trust"><div class="wrap"><ul>{trust_html}</ul>
{src_line}</div></section>
{block('하는 일', f'<ol class="areas">{area_html}</ol><p class="more">{arrow_link("work.html", "사업 내용과 실적 보기")}</p>', '주민이 만든 조합이 마을에 필요한 일을 합니다.', sid='what')}
{care_band}
<section class="shopband"><div class="wrap sgrid">
  <div><p class="kicker">판촉물·기념품 사업</p><h2>{SHOP_LABEL}</h2>
  <p>단체 행사와 기관 홍보에 필요한 판촉물·기념품 사업을 수행하고 있습니다. 사업 수익은 지역사회에 환원합니다.</p></div>
  <div class="sbtn">{shop_link("쇼핑몰 바로가기", "btn yellow")}</div>
  {mosaic("mosaic bg")}
</div></section>
{block('최근 소식', news_rows(NEWS, 3) + f'<p class="more">{arrow_link("news.html", "소식 전체 보기")}</p>', '조합의 활동은 네이버 블로그와 함께 이곳에도 올라옵니다. 글을 누르면 블로그가 새 창으로 열립니다.', sid='news')}
{trust_blk}
{block('함께해 주세요', f'<ul class="joins">{join_html}</ul>', '', sid='join')}
"""
    return layout("index.html", "", body)


def page_about():
    officer_rows = ""
    for role in ("이사장", "이사", "감사"):
        names = [o["name"] for o in OFFICERS if o["role"] == role]
        if names:
            cell = E(names[0]) if len(names) == 1 else '<ul class="inline">' + "".join(f"<li>{E(n)}</li>" for n in names) + "</ul>"
            officer_rows += f"<div><dt>{role}</dt><dd>{cell}</dd></div>"
    tl = "".join(f'<li><time>{E(t["date"])}</time><span>{E(t["text"])}</span></li>' for t in TIMELINE)
    for t in TIMELINE:
        if t.get("review"):
            WARN.append(f'연혁 확인 필요 [{t["date"]}]: {t["review"]}')
    facts = f"""<dl class="facts">
<div><dt>설립일</dt><dd>{E(SITE['founded'])}</dd></div>
<div><dt>조합원</dt><dd>{SITE['members']}명</dd></div>
<div><dt>소재지</dt><dd>{E(SITE['address'])}</dd></div>
<div><dt>협력 협약</dt><dd>{len(PARTNERS['mou'])}건</dd></div></dl>"""
    body = page_head("우리는", f"{E(SITE['name'])}은 원당 도시재생 지역 주민들이 모여 만든 마을관리 사회적협동조합입니다.", "우리는") + f"""
<section class="blk"><div class="wrap">
{facts}
<div class="sec-head"><h2>비전</h2></div>
<div class="trio"><div><h3>살피다</h3><p>마을과 공동체, 그리고 사람을 보고 소외된 곳을 두루 살핍니다.</p></div>
<div><h3>익히다</h3><p>배우고 익혀 마을에 필요한 재화와 콘텐츠를 기획합니다.</p></div>
<div><h3>행하다</h3><p>우리가 사는 도시를, 마을을, 사람을 위한 모든 것을 행합니다.</p></div></div>
</div></section>
<section class="blk soft"><div class="wrap"><div class="sec-head"><h2>임원</h2></div>
<dl class="officers">{officer_rows}</dl></div></section>
<section class="blk"><div class="wrap"><div class="sec-head"><h2>연혁</h2></div><ol class="timeline">{tl}</ol></div></section>
<section class="blk soft"><div class="wrap"><div class="sec-head"><h2>신뢰 경영</h2><p class="sub">협력 협약과 언론 보도로 조합의 활동을 확인하실 수 있습니다.</p></div>
<div class="two"><div><h3>협력 협약</h3>{mou_list()}{award_block()}</div><div><h3>언론 보도</h3>{press_list()}</div></div></div></section>"""
    return layout("about.html", "우리는", body, f"{SITE['name']}의 비전, 임원, 연혁, 협력 협약, 언론 보도")


def page_work():
    areas = ""
    for a in WORK["areas"]:
        items = "".join(f"<li>{E(i)}</li>" for i in a["items"])
        link = f'<p>{shop_link("쇼핑몰 바로가기", "btn solid sm")}</p>' if a.get("link") else ""
        title = f'판촉물은 배다리' if a.get("link") else E(a["title"])
        areas += f'<article class="area" id="{a["id"]}"><h3>{title}</h3><p>{E(a["lead"])}</p><ul class="check">{items}</ul>{link}</article>'
    rows = "".join(
        f'<tr><td data-l="기간">{E(r["period"])}</td><td data-l="사업명">{E(r["title"])}</td><td data-l="발주·협력처">{E(r["client"])}</td></tr>' for r in WORK["records"])
    body = page_head("하는 일", "교육, 집수리, 행사, 지역활성화, 판촉물 사업을 합니다.", "하는 일") + f"""
<section class="blk"><div class="wrap"><div class="areas2">{areas}</div></div></section>
<section class="blk soft"><div class="wrap"><div class="sec-head"><h2>사업 실적</h2></div>
<div class="scroll"><table class="data resp"><thead><tr><th>기간</th><th>사업명</th><th>발주·협력처</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="note">2023년 소개자료 기준이며 최신 실적은 순차적으로 추가합니다.</p></div></section>"""
    return layout("work.html", "하는 일", body, "교육서비스, 집수리, 행사대행, 지역활성화, 판촉물 사업과 실적")


def page_care():
    c = CARE
    cmp_rows = "".join(f'<tr><th scope="row">{E(a)}</th><td>{E(b_)}</td><td class="hl">{E(d)}</td></tr>' for a, b_, d in c["compare"])
    steps = "".join(f'<li><b>{E(n)}</b><span>{E(d)}</span></li>' for n, d in c["process"])
    net = "".join(f'<li><b>{E(n["name"])}</b><span class="meta">{E(n["role"])}</span><span class="st">{E(n["status"])}</span></li>' for n in c["network"])
    road = "".join(f'<li><span class="ph">{E(p)}</span><b>{E(t)}</b><span>{E(d)}</span></li>' for p, t, d in c["roadmap"])
    ph = c.get("photo")
    photo = (f'<figure class="photo"><img src="{E(ph["file"])}" alt="{E(ph["alt"])}" width="1400" height="787" loading="lazy">'
             f'<figcaption>{E(ph["caption"])}</figcaption></figure>') if ph else ""
    body = page_head(E(c["title"]), E(c["lead"]), "통합돌봄") + f"""
<section class="blk"><div class="wrap"><div class="sec-head"><h2>왜 통합돌봄인가</h2></div>
<p class="prose">{E(c['why'])}</p>
<p class="status-note"><b>추진 계획입니다.</b> 아래 내용은 조합이 준비하고 있는 계획이며, 협의와 승인 상황에 따라 달라질 수 있습니다.</p></div></section>
<section class="blk soft"><div class="wrap"><div class="sec-head"><h2>배다리가 그리는 모델</h2><p class="sub">돌봄을 기관이 아니라 어르신의 생활권에서 시작합니다.</p></div>
<div class="scroll"><table class="data cmp"><thead><tr><th></th><th>기존 방식</th><th>배다리 모델</th></tr></thead><tbody>{cmp_rows}</tbody></table></div></div></section>
<section class="blk"><div class="wrap"><div class="sec-head"><h2>돌봄은 이렇게 이어집니다</h2></div><ol class="steps big">{steps}</ol></div></section>
<section class="blk soft"><div class="wrap two">
<div><div class="sec-head"><h2>의료·보건 협력</h2><p class="sub">지역 의료·보건 기관과 함께 돌봄을 설계합니다.</p></div><ul class="plain net">{net}</ul>{photo}</div>
<div><div class="sec-head"><h2>수익을 마을에 돌려드립니다</h2></div><p class="prose">{E(c['returns'])}</p></div>
</div></section>
<section class="blk"><div class="wrap"><div class="sec-head"><h2>추진 로드맵</h2></div><ol class="road">{road}</ol>
<p class="cta-line">돌봄 협력, 자원봉사, 의견 제안을 기다립니다. {arrow_link("join.html#request", "문의하기")}</p></div></section>"""
    return layout("care.html", "통합돌봄", body, c["short"])


def page_news():
    cats = sorted({n["category"] for n in NEWS if n["category"]})
    btns = '<button class="chip on" data-cat="">전체</button>' + "".join(
        f'<button class="chip" data-cat="{E(c)}">{E(c)}</button>' for c in cats)
    body = page_head("소식", "조합 블로그의 최근 글입니다. 글을 누르면 블로그가 새 창으로 열립니다.", "소식") + f"""
<section class="blk"><div class="wrap"><div class="chips" role="group" aria-label="분류">{btns}</div>
<div id="newslist">{news_rows(NEWS)}</div>
<p class="more">{arrow_link(SITE['sns'].get('blog') or 'https://blog.naver.com/baedaricoop', '네이버 블로그에서 더 보기', True)}</p></div></section>"""
    return layout("news.html", "소식", body, "배다리마을관리 사회적협동조합 활동 소식")


def page_join():
    ep = SITE["form_endpoint"]
    if not ep:
        WARN.append("문의 폼 전송 주소(site.json form_endpoint)가 비어 있어 폼은 이메일 보내기로 동작합니다.")
    guide = SITE.get("donation_guide", "").strip()
    if SITE["donation_open"] and guide:
        donate = f"""<p>{E(SITE['name'])}은 공익법인(구 지정기부금단체)으로 지정되어 후원금에 대한 <b>기부금영수증</b>을 발급합니다.
후원금 모집액과 사용 내역은 <a href="open.html#donations">투명경영</a> 페이지에 공개합니다.</p>
<p><b>후원 방법</b><br>{E(guide).replace(chr(10), "<br>")}</p>"""
    else:
        donate = """<p>공익법인(구 지정기부금단체)으로서 후원금 모집·사용 내역을 투명하게 공개한 뒤 후원 안내를 열겠습니다. 후원에 관심 있으신 분은 아래 문의로 연락 주세요.</p>"""
    form = f"""<form id="inquiry" class="form" data-endpoint="{E(ep)}" data-mailto="{E(SITE['email'])}">
<div class="f2"><label>문의 구분
<select name="type"><option>조합원 가입</option><option>후원</option><option>봉사</option><option>교육·행사 등 사업 의뢰</option><option>기타</option></select></label>
<label>이름·기관명 <input name="name" required autocomplete="name"></label></div>
<label>연락처 (전화 또는 이메일) <input name="contact" required></label>
<label>문의 내용 <textarea name="message" rows="5" required></textarea></label>
<label class="chk"><input type="checkbox" name="agree" required><span>개인정보 수집·이용에 동의합니다. 수집 항목: 이름, 연락처, 문의 내용 / 목적: 문의 응대 / 보관: 응대 완료 후 1년</span></label>
<p class="hp" aria-hidden="true"><label>비워 두세요 <input name="website" tabindex="-1" autocomplete="off"></label></p>
<p class="note"><a href="privacy.html">개인정보처리방침 보기</a></p>
<button class="btn solid" type="submit">문의 보내기</button>
<p class="status" role="status" aria-live="polite"></p></form>"""
    body = page_head("함께하기", "조합원 가입, 후원, 봉사, 사업 의뢰를 안내합니다.", "함께하기") + f"""
<section class="blk"><div class="wrap">
<div class="joinlist">
<article id="member"><h2>조합원 가입</h2><p>마을과 함께하고 싶은 분이면 누구나 문의하실 수 있습니다. 가입 절차와 출자금 안내는 문의하시면 알려드립니다.</p></article>
<article id="donate"><h2>후원하기</h2>{donate}</article>
<article id="volunteer"><h2>봉사 참여</h2><p>마을정원 가꾸기, 꽃씨 심기 등 마을 행사의 자원봉사를 받습니다. 모집 소식은 <a href="news.html">소식</a>에서 확인하세요.</p></article>
<article id="request"><h2>사업 의뢰</h2><p>교육, 집수리, 행사 대행 등 협력 문의를 받습니다. 판촉물은 {ext(utm(SITE['shop_url']), '판촉물은 배다리 쇼핑몰')}에서 주문하실 수 있습니다.</p></article>
</div></div></section>
<section class="blk soft" id="contact"><div class="wrap two">
<div><div class="sec-head"><h2>문의하기</h2></div>{form}</div>
<div><div class="sec-head"><h2>오시는 길</h2></div><p>{E(SITE['address'])}</p><p>전화 {E(SITE['phone'])}<br>{E(SITE['email'])}</p></div>
</div></section>"""
    return layout("join.html", "함께하기", body, "조합원 가입, 후원, 봉사, 사업 의뢰 안내")


def page_open():
    docs = "".join(
        f'<li><a href="{E(d["file"].replace("files/", ""))}" target="_blank" rel="noopener noreferrer"><b>{E(d["title"])}</b>'
        f'<span>{E(d["note"])}</span><span class="go" aria-hidden="true">↗</span><span class="sr"> (새 창)</span></a></li>' for d in OPEN["docs"])
    rows = ""
    for y in OPEN["years"]:
        if "total_in" in y:
            rows += (f'<tr><td data-l="사업연도">{E(y["year"])}</td><td data-l="모금액">{E(y["total_in"])}</td><td data-l="사용액">{E(y["total_out"])}</td>'
                     f'<td data-l="잔액">{E(y["balance"])}</td><td data-l="영수증 발급(건)">{E(y.get("receipts", ""))}</td><td data-l="자료">'
                     + (f'<a href="{E(y["file"])}" target="_blank" rel="noopener noreferrer">결산서류</a>' if y.get("file") else "") + "</td></tr>")
        else:
            rows += f'<tr><td data-l="사업연도">{E(y["year"])}</td><td colspan="5">{E(y["status"])}</td></tr>'
    ntc = "".join(
        f'<li><b>{E(str(n["title"]))}</b><span class="meta">{E(str(n.get("date", "")))}</span><span class="d">{E(str(n.get("body", "")))}</span>'
        + (f'<a href="{E(n["file"])}" target="_blank" rel="noopener noreferrer">첨부 보기</a>' if n.get("file") else "") + '</li>'
        for n in OPEN.get("notices", []))
    ntc = f'<ul class="plain notices">{ntc}</ul>' if ntc else '<p class="note">현재 게시된 공고가 없습니다.</p>'
    body = page_head("투명경영", "조합의 정관, 공고, 후원금 모집·사용 내역을 공개합니다.", "투명경영") + f"""
<section class="blk"><div class="wrap"><div class="sec-head"><h2>정관·운영 자료</h2></div><ul class="docs">{docs}</ul></div></section>
<section class="blk" id="notices"><div class="wrap"><div class="sec-head"><h2>조합 공고</h2></div>{ntc}</div></section>
<section class="blk soft" id="donations"><div class="wrap"><div class="sec-head"><h2>후원금 모집·사용 내역</h2>
<p class="sub">{E(OPEN['deadline_note'])} 사업연도는 매년 {E(OPEN['fiscal_year_end'])}에 종료됩니다.</p></div>
<div class="scroll"><table class="data resp"><thead><tr><th>사업연도</th><th>모금액</th><th>사용액</th><th>잔액</th><th>영수증 발급(건)</th><th>자료</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="note">공개 내용은 조합이 확인해 게시하며 <b>기부자 개인정보는 공개하지 않습니다.</b> 결산서류와 기부금 모금액·활용실적은 국세청 {ext('https://www.hometax.go.kr', '홈택스')}에도 함께 공시합니다.</p></div></section>"""
    return layout("open.html", "투명경영", body, "정관, 결산서류, 후원금 모집·사용 내역 공개")


def page_privacy():
    c = E(SITE["name"])
    body = page_head("개인정보처리방침", f"{c}은 개인정보 보호법에 따라 개인정보를 필요한 만큼만 수집하고 안전하게 관리합니다.", "개인정보처리방침") + f"""
<section class="blk"><div class="wrap legal">
<h2>1. 처리 목적, 항목, 보유 기간</h2>
<div class="scroll"><table class="data"><thead><tr><th>업무</th><th>수집 항목</th><th>목적</th><th>보유 기간</th></tr></thead><tbody>
<tr><td>홈페이지 문의</td><td>이름·기관명, 연락처, 문의 내용, 유입 경로</td><td>문의 확인과 답변</td><td>응대 완료 후 1년</td></tr>
<tr><td>후원·기부금영수증</td><td>기부자 성명, 연락처, 후원 금액·일자, 영수증 발급 정보(법령이 요구하는 항목)</td><td>후원 관리, 영수증 발급, 법정 의무 이행</td><td>정관과 관계 법령에 따라 5년 이상</td></tr>
</tbody></table></div>
<h2>2. 제3자 제공</h2><p>법령에 근거가 있거나 본인이 동의한 경우를 제외하고 개인정보를 제3자에게 제공하지 않습니다. 기부금영수증 관련 자료는 법령에 따라 국세청에 제출할 수 있습니다.</p>
<h2>3. 외부 서비스 이용</h2><p>문의 접수와 보관에는 Google LLC의 스프레드시트와 Apps Script를, 홈페이지 제공에는 GitHub, Inc.의 GitHub Pages를, 글꼴 제공에는 jsDelivr를 이용합니다. 이 과정에서 입력한 문의 내용이나 접속 기록(IP 주소 등)이 국외 서버에서 처리될 수 있습니다.</p>
<h2>4. 파기</h2><p>보유 기간이 지나거나 목적을 달성하면 지체 없이 삭제합니다.</p>
<h2>5. 정보주체의 권리</h2><p>본인의 개인정보 열람, 정정, 삭제, 처리 정지를 언제든지 요청할 수 있습니다. 아래 연락처로 요청해 주세요.</p>
<h2>6. 안전 조치</h2><p>개인정보가 담긴 문서는 권한이 있는 담당자만 접근하도록 관리합니다.</p>
<h2>7. 자동 수집 장치</h2><p>이 홈페이지는 방문자를 추적하는 쿠키나 분석 도구를 사용하지 않습니다.</p>
<h2>8. 개인정보 문의처</h2><p>{c} 사무국<br>{E(SITE["address"])}<br>전화 {E(SITE["phone"])} · {E(SITE["email"])}</p>
<p>개인정보 침해 신고나 상담은 개인정보침해신고센터(국번 없이 118)에서도 할 수 있습니다.</p>
</div></section>"""
    return layout("privacy.html", "개인정보처리방침", body, "개인정보처리방침")


def page_404():
    body = page_head("페이지를 찾을 수 없습니다", "주소가 바뀌었거나 없는 페이지입니다.", "안내") + \
        '<section class="blk"><div class="wrap"><a class="btn solid" href="index.html">홈으로 가기</a></div></section>'
    return layout("404.html", "페이지를 찾을 수 없습니다", body, base=True)


PAGES = {"privacy.html": page_privacy, "index.html": page_index, "about.html": page_about, "work.html": page_work,
         "care.html": page_care, "news.html": page_news, "join.html": page_join, "open.html": page_open}


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    for name, fn in PAGES.items():
        (DIST / name).write_text(fn(), encoding="utf-8")
    (DIST / "404.html").write_text(page_404(), encoding="utf-8")
    for f in STATIC.iterdir():
        shutil.copy(f, DIST / f.name)
    urls = "".join(f"<url><loc>{SITE['domain']}/{'' if n == 'index.html' else n}</loc></url>" for n in PAGES)
    (DIST / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', encoding="utf-8")
    (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE['domain']}/sitemap.xml\n", encoding="utf-8")
    for d in (SITE, PEOPLE, PARTNERS, WORK, OPEN, CARE):
        for r in d.get("review", []):
            WARN.append(r)
    print(f"빌드 완료: {len(PAGES)}쪽 → {DIST}")
    if WARN:
        print("\n[게시 전 확인할 것]")
        for w in dict.fromkeys(WARN):
            print(" -", w)


if __name__ == "__main__":
    main()
