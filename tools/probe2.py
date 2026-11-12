import re, urllib.request, urllib.parse
def get(u, data=None):
    req = urllib.request.Request(u, data=data, headers={"User-Agent": "Mozilla/5.0 govland-tracker"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")
for u in ("https://www.miamidade.gov/govaction/keywordsearch.asp", "https://www.miamidade.gov/govaction/searchleg.asp"):
    h = get(u)
    for m in re.finditer(r"<form[^>]*>|<input[^>]*>|<select[^>]*>|<textarea[^>]*>", h, re.I):
        print("FORM", u[-20:], m.group(0)[:220])
# try a keyword search the likely way, print result shape
for q in ("https://www.miamidade.gov/govaction/keywordsearch.asp?Action=Search&searchtext=Flagler+TOC&begindate=01-01-2026&enddate=11-12-2026",):
    try:
        h = get(q); print("TRY GET len", len(h)); print("TRY GET matters", re.findall(r"matter\.asp\?matter=(\d+)[^\"']*", h)[:10])
    except Exception as e:
        print("TRY GET fail", e)
