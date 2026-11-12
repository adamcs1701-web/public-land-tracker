#!/usr/bin/env python3
"""Commission records check.

Finds county commission items that name one of our parcels, by folio number or street address,
so a parcel that has already been leased, sold or otherwise committed can be spotted.

  Miami-Dade: the county's legislative search (titles), then each item's full text.
  Broward:    the county's Legistar web service (titles), then each item's full text.

Writes data/records_cache.json (what was read from each item, so later runs only read new ones)
and docs/records.json (the matches the site shows).  Usage:  python3 tools/records.py
"""
import datetime, html, json, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "records_cache.json")
OUT = os.path.join(ROOT, "docs", "records.json")
TODAY = datetime.date.today()

# Title words that make an item worth reading. Matching is done on the full text afterwards.
SEARCH_TERMS = ["lease", "convey", "surplus", "deed", "easement", "license agreement", "development agreement",
                "interlocal", "real property", "sale of", "dispos", "right of entry", "joint development", "option to purchase"]
# Words shown on the site, and which of them suggest the land is committed.
TAGS = [("ground lease", r"GROUND LEASE"), ("lease", r"\b(SUB)?LEAS(E|ES|ED|ING)\b"), ("conveyance", r"\bCONVEY"),
        ("deed", r"\bDEEDS?\b"), ("sale", r"\bSALE OF\b|\bSELL\b|\bPURCHASE AND SALE\b"), ("surplus", r"\bSURPLUS\b"),
        ("easement", r"\bEASEMENTS?\b"), ("license", r"\bLICENSE AGREEMENT|REVOCABLE LICENSE"),
        ("development agreement", r"DEVELOPMENT AGREEMENT"), ("interlocal", r"\bINTERLOCAL\b"),
        ("option to purchase", r"OPTION TO PURCHASE"), ("right of entry", r"RIGHT OF ENTRY"), ("disposition", r"\bDISPOS(E|AL|ITION)\b")]
COMMITTED = {"ground lease", "lease", "conveyance", "deed", "sale", "license", "development agreement", "option to purchase"}

DIRS = {"N": "N", "S": "S", "E": "E", "W": "W", "NE": "NE", "NW": "NW", "SE": "SE", "SW": "SW", "NORTH": "N", "SOUTH": "S",
        "EAST": "E", "WEST": "W", "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW"}
SUFFIX = {"STREET": "ST", "ST": "ST", "AVENUE": "AVE", "AVE": "AVE", "AV": "AVE", "ROAD": "RD", "RD": "RD", "BOULEVARD": "BLVD",
          "BLVD": "BLVD", "DRIVE": "DR", "DR": "DR", "COURT": "CT", "CT": "CT", "TERRACE": "TER", "TER": "TER", "PLACE": "PL",
          "PL": "PL", "HIGHWAY": "HWY", "HWY": "HWY", "PARKWAY": "PKWY", "PKWY": "PKWY", "WAY": "WAY", "LANE": "LN", "LN": "LN",
          "CIRCLE": "CIR", "CIR": "CIR", "TRAIL": "TRL", "TRL": "TRL", "CAUSEWAY": "CSWY", "CSWY": "CSWY"}
_SUF = "|".join(sorted(SUFFIX, key=len, reverse=True))
_DIR = "|".join(sorted(DIRS, key=len, reverse=True))
ADDR_RX = re.compile(r"\b(\d{1,6})\s+((?:(?:%s)\.?\s+)?(?:[A-Z0-9][A-Z0-9'\-]*\.?\s+){0,3}?)(%s)\b\.?(?:\s+(%s)\b)?" % (_DIR, _SUF, _DIR))
FOLIO_RX = re.compile(r"(?<![\d-])\d{2,4}(?:[- ]\d{1,4}){2,4}(?![\d-])|(?<!\d)\d{12,13}(?!\d)")


def addr_key(num, middle, suffix="", trail=""):
    """'9250', 'W FLAGLER', 'ST' -> '9250|FLAGLER'. Numbered streets keep direction and type: '100|NE 1 AVE'."""
    toks = [t.strip(".") for t in middle.upper().split() if t.strip(".")]
    d = ""
    if toks and toks[0] in DIRS:
        d = DIRS[toks.pop(0)]
    toks = [re.sub(r"^(\d+)(ST|ND|RD|TH)$", r"\1", t) for t in toks]
    if not toks:
        return None
    core = " ".join(toks)
    if core.isdigit():                       # "NE 1 AVE" and "NW 1 ST" are different streets
        core = " ".join(x for x in (d or (DIRS.get(trail, "") if trail else ""), core, SUFFIX.get(suffix, suffix)) if x)
    return "%s|%s" % (int(num), core)


def roll_addr_key(a):
    """Tax-roll style '9250 W FLAGLER ST' or '10071 60TH ST N'."""
    toks = re.sub(r"[^A-Z0-9 ]", " ", (a or "").upper()).split()
    if len(toks) < 2 or not toks[0].isdigit():
        return None
    num, rest = toks[0], toks[1:]
    trail = ""
    if len(rest) > 1 and rest[-1] in DIRS:
        trail = rest.pop()
    suf = ""
    if len(rest) > 1 and rest[-1] in SUFFIX:
        suf = rest.pop()
    return addr_key(num, " ".join(rest), suf, trail)


def text_addr_keys(t):
    out = set()
    T = re.sub(r"\b([NS])\.\s?([EW])\.", r"\1\2", t.upper())          # N.E. -> NE
    for m in ADDR_RX.finditer(T):
        k = addr_key(m.group(1), m.group(2), m.group(3), m.group(4) or "")
        if k:
            out.add(k)
    return out


def text_folios(t):
    out = set()
    for m in FOLIO_RX.finditer(t):
        d = re.sub(r"\D", "", m.group(0))
        if 12 <= len(d) <= 13:
            out.add(d)
    return out


def tags_of(t):
    T = t.upper()
    return [name for name, rx in TAGS if re.search(rx, T)]


def http(url, data=None, tries=4, timeout=90):
    last = None
    for i in range(tries):
        try:
            body = urllib.parse.urlencode(data).encode() if data else None
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "Mozilla/5.0 public-land-tracker",
                                                                  "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError("%s: %s" % (url[:120], last))


def plain(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def us_date(s):
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    return "%s-%02d-%02d" % (m.group(3), int(m.group(1)), int(m.group(2))) if m else None


# ---------------------------------------------------------------- Miami-Dade
MD = "https://www.miamidade.gov/govaction/"


def md_search(term, d1, d2, depth=0):
    h = http(MD + "keywordsearch.asp", {"mtintro": d1.strftime("%m-%d-%Y"), "mtintro2": d2.strftime("%m-%d-%Y"),
                                        "mttitle": term, "btnSubmit": "Search"})
    ids = set(re.findall(r"matter\.asp\?matter=(\d+)", h))
    if len(ids) >= 200 and depth < 4 and (d2 - d1).days > 20:      # the result list may be capped: split the range
        mid = d1 + (d2 - d1) / 2
        return md_search(term, d1, mid, depth + 1) | md_search(term, mid + datetime.timedelta(days=1), d2, depth + 1)
    return ids


LABELS = ["File Number", "File Type", "Status", "Version", "Reference", "Control", "File Name", "Introduced",
          "Cost", "Final Action", "Agenda Date", "Agenda Item Number", "Notes", "Title", "Indexes", "Sponsors", "Sunset Provision"]


def md_item(fid):
    yf = "Y20" + fid[:2] if fid[:2].isdigit() else "Y%d" % TODAY.year
    url = MD + "matter.asp?matter=%s&file=true&yearFolder=%s" % (fid, yf)
    t = plain(http(url))
    f = {}
    for i, lab in enumerate(LABELS):
        m = re.search(r"%s:\s*(.*?)\s*(?=(?:%s):|$)" % (re.escape(lab), "|".join(map(re.escape, LABELS[i + 1:])) or "$^"), t)
        if m:
            f[lab] = m.group(1)[:600]
    body_from = t.find("Title:")
    body = t[body_from:] if body_from >= 0 else t
    return {"gov": "Miami-Dade County Commission", "file": fid, "type": f.get("File Type", ""), "status": f.get("Status", ""),
            "reference": f.get("Reference", ""), "name": f.get("File Name", ""), "title": (f.get("Title") or f.get("File Name") or "")[:400],
            "intro": us_date(f.get("Introduced")), "final": us_date(f.get("Final Action")),
            "url": MD + "matter.asp?matter=%s&file=true&yearFolder=%s" % (fid, yf),
            "pdf": MD + "legistarfiles/Matters/%s/%s.pdf" % (yf, fid),
            "folios": sorted(text_folios(body)), "addrs": sorted(text_addr_keys(body)), "tags": tags_of(body), "read": TODAY.isoformat()}


def miami_dade(cache, start_year):
    found = set()
    for y in range(start_year, TODAY.year + 1):
        d1, d2 = datetime.date(y, 1, 1), min(datetime.date(y, 12, 31), TODAY)
        for term in SEARCH_TERMS:
            try:
                ids = md_search(term, d1, d2)
            except Exception as e:
                print("  miami-dade search failed: %s %d (%s)" % (term, y, str(e)[:80]), flush=True)
                continue
            found |= ids
        print("  miami-dade %d: %d items so far" % (y, len(found)), flush=True)
    recent = (TODAY - datetime.timedelta(days=200)).isoformat()
    todo = [f for f in sorted(found) if f not in cache or (cache[f].get("intro") or "9999") >= recent]
    print("  miami-dade: %d items found, %d to read" % (len(found), len(todo)), flush=True)

    def one(fid):
        try:
            return fid, md_item(fid), None
        except Exception as e:
            return fid, None, str(e)[:120]
    bad = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for n, (fid, it, err) in enumerate(pool.map(one, todo), 1):
            if it:
                cache[fid] = it
            else:
                bad += 1
            if n % 500 == 0:
                print("  miami-dade: read %d of %d" % (n, len(todo)), flush=True)
    print("  miami-dade: %d items could not be read" % bad, flush=True)
    sample = cache.get("261810")
    if sample:
        print("  sample 261810:", json.dumps({k: sample[k] for k in ("type", "status", "reference", "intro", "final", "folios", "addrs", "tags")})[:400], flush=True)


# ---------------------------------------------------------------- Broward (Legistar)
LG = "https://webapi.legistar.com/v1/broward/"


def broward(cache):
    flt = " or ".join("substringof('%s',MatterTitle)" % t for t in SEARCH_TERMS)
    sel = "MatterId,MatterGuid,MatterFile,MatterTitle,MatterTypeName,MatterStatusName,MatterIntroDate,MatterPassedDate,MatterAgendaDate"
    rows, skip = [], 0
    while True:
        q = urllib.parse.urlencode({"$filter": flt, "$select": sel, "$top": 1000, "$skip": skip})
        page = json.loads(http(LG + "matters?" + q))
        rows += page
        if len(page) < 1000:
            break
        skip += 1000
    print("  broward: %d items found" % len(rows), flush=True)
    recent = (TODAY - datetime.timedelta(days=200)).isoformat()

    def one(m):
        key = str(m["MatterId"])
        c = cache.get(key)
        intro = (m.get("MatterIntroDate") or "")[:10] or None
        meta = {"gov": "Broward County Commission", "file": m.get("MatterFile") or key, "type": m.get("MatterTypeName") or "",
                "status": m.get("MatterStatusName") or "", "title": (m.get("MatterTitle") or "")[:400], "intro": intro,
                "final": (m.get("MatterPassedDate") or "")[:10] or None,
                "url": "https://broward.legistar.com/LegislationDetail.aspx?ID=%s&GUID=%s" % (key, m.get("MatterGuid") or "")}
        if c and (c.get("intro") or "9999") < recent:
            c.update(meta)
            return key, c, None
        try:
            vers = json.loads(http(LG + "matters/%s/versions" % key))
            txt = ""
            if vers:
                tid = max(vers, key=lambda v: int(v.get("Value") or 0))["Key"]
                txt = json.loads(http(LG + "matters/%s/texts/%s" % (key, tid))).get("MatterTextPlain") or ""
            body = (m.get("MatterTitle") or "") + " " + txt
            meta.update(folios=sorted(text_folios(body)), addrs=sorted(text_addr_keys(body)), tags=tags_of(body), read=TODAY.isoformat())
            return key, meta, None
        except Exception as e:
            return key, None, str(e)[:120]
    bad = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for key, it, err in pool.map(one, rows):
            if it:
                cache[key] = it
            else:
                bad += 1
    print("  broward: %d items could not be read" % bad, flush=True)


# ---------------------------------------------------------------- matching
def hot_tags(it):
    """Commitment judged from the item's title, not incidental words in its body. A conveyance of an
    easement (utility easements and the like) does not take the land itself off the table."""
    t = tags_of((it.get("title") or "") + " " + (it.get("name") or ""))
    hot = [x for x in t if x in COMMITTED]
    if "easement" in t and not set(hot) & {"ground lease", "lease", "deed", "sale", "development agreement", "option to purchase"}:
        hot = [x for x in hot if x not in ("conveyance", "license")]
    T = ((it.get("title") or "") + " " + (it.get("name") or "")).upper()
    acquiring = re.search(r"\bACCEPT(ANCE|ING)?\b|\bACQUI(RE|SITION|RING)\b|\bPURCHASE BY (THE |MIAMI-DADE |BROWARD )?COUNTY|\bDONATION\b", T)
    if acquiring and not set(hot) & {"ground lease", "lease"} and "PURCHASE AND SALE" not in T:
        hot = [x for x in hot if x not in ("conveyance", "deed", "sale")]      # land coming in, not going out
    return hot


MAX_ADDR_ITEMS = 12     # an address cited in more items than this is boilerplate (a government center), not a parcel


def match(parcels, cache):
    items, by_parcel = {}, {}
    for county, store in cache.items():
        if county.startswith("_"):
            continue
        fol, adr = {}, {}
        for p in parcels:
            if p["county"] != county:
                continue
            k = p["county"] + "|" + p["id"]
            fol.setdefault(re.sub(r"\D", "", p["id"]), []).append(k)
            ak = roll_addr_key(p.get("address"))
            if ak:
                adr.setdefault(ak, []).append(k)
        df = {}
        for it in store.values():
            for a in set(it.get("addrs", [])):
                df[a] = df.get(a, 0) + 1
        for ref, it in store.items():
            hits = {}
            for f in it.get("folios", []):
                for k in fol.get(f, []):
                    hits[k] = "folio"
            for a in it.get("addrs", []):
                if df.get(a, 0) > MAX_ADDR_ITEMS:
                    continue
                for k in adr.get(a, [])[:6]:             # an address shared by many parcels is too vague to report
                    hits.setdefault(k, "address")
            if hits:
                rid = county + ":" + ref
                items[rid] = {k: it.get(k) for k in ("gov", "file", "type", "status", "reference", "title", "name", "intro", "final", "url", "pdf", "tags")}
                items[rid]["hot"] = hot_tags(it)
                items[rid]["n"] = len(hits)
                for k, how in hits.items():
                    by_parcel.setdefault(k, []).append([rid, how])
    return items, by_parcel


def main():
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    parcels = json.load(open(os.path.join(ROOT, "data", "parcels.json")))["parcels"]
    cov = cache.setdefault("_coverage", {})
    if "--match-only" not in sys.argv:
        for county, fn in (("miami-dade", lambda c: miami_dade(c, 2005)), ("broward", broward)):
            store = cache.setdefault(county, {})
            t0 = time.time()
            try:
                fn(store)
                dates = sorted(i["intro"] for i in store.values() if i.get("intro"))
                cov[county] = {"items": len(store), "from": dates[0] if dates else None, "to": dates[-1] if dates else None,
                               "checked": TODAY.isoformat(), "ok": True}
            except Exception as e:
                print("  %s FAILED: %s" % (county, e), flush=True)
                cov.setdefault(county, {})["ok"] = False
            print("%s: %d items on file, %.0f min" % (county, len(store), (time.time() - t0) / 60), flush=True)
            json.dump(cache, open(CACHE, "w"), separators=(",", ":"))      # save progress after each county
    items, by_parcel = match(parcels, cache)
    doc = {"generated_at": TODAY.isoformat(), "coverage": cov, "items": items, "by_parcel": by_parcel,
           "committed_tags": sorted(COMMITTED)}
    json.dump(doc, open(OUT, "w"), separators=(",", ":"))
    n_com = sum(1 for k, refs in by_parcel.items() if any(items[r]["hot"] for r, _ in refs))
    print("matched: %d parcels named in %d items; %d of those parcels in an item whose title is a lease, sale or conveyance" % (len(by_parcel), len(items), n_com), flush=True)


if __name__ == "__main__":
    main()
