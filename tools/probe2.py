import re, urllib.request, urllib.parse, html as H
def get(u, data=None):
    req = urllib.request.Request(u, data=urllib.parse.urlencode(data).encode() if data else None, headers={"User-Agent": "Mozilla/5.0 govland-tracker", "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("utf-8", "replace")
def text(h): return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", h))))
for kw, d1, d2 in (("9250 West Flagler", "01-01-2020", "11-12-2026"), ("Flagler TOC", "01-01-2026", "11-12-2026"), ("lease", "10-01-2026", "11-12-2026"), ("30-4004-024-0010", "01-01-2015", "11-12-2026")):
    try:
        h = get("https://www.miamidade.gov/govaction/keywordsearch.asp", {"mtintro": d1, "mtintro2": d2, "mttitle": kw, "btnSubmit": "Search"})
        ids = re.findall(r"matter\.asp\?matter=(\d+)([^\"'<> ]*)", h)
        print("KW", repr(kw), "len", len(h), "hits", len(ids), ids[:6])
        i = h.find("matter.asp?matter=")
        if i > 0: print("ROW", text(h[i-300:i+700])[:500])
    except Exception as e:
        print("KW FAIL", kw, e)
h = get("https://www.miamidade.gov/govaction/matter.asp?matter=261810&file=true&yearFolder=Y2026")
t = text(h)
print("PAGE folios", re.findall(r"\b\d{2}-\d{4}-\d{3}-\d{4}\b", t)[:8], "| has 9250:", "9250" in t, "| len", len(t))
