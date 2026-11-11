"""Source-independent logic: who owns it, what it is, and what changed."""
import csv, json, os, re
import providers

USE_LABELS = {80: "Vacant governmental", 81: "Military", 82: "Forest, park, recreation",
              83: "Public school", 84: "College", 85: "Hospital", 86: "County (other)",
              87: "State (other)", 88: "Federal (other)", 89: "Municipal (other)",
              90: "Government land leased to private party"}

# First match wins, so order matters (school boards before counties, etc.).
OWNER_RULES = [
    ("school", r"SCHOOL (BOARD|DISTRICT)|BOARD OF PUBLIC INSTRUCTION|\bSBBC\b"),
    ("federal", r"\bU ?S DEPT|\bU ?S ARMY|ARMY CORPS|CORPS? OF ENG|\bUSA\b|BIG CYPRESS|NATL PARK|NATIONAL PARK|DEPT OF (THE )?INTERIOR|UNITED STATES|\bU ?S ?A\b|\bU S GOVERNMENT|US DEPT|FEDERAL AVIATION|POSTAL SERVICE"),
    ("state", r"\bSTATE OF FL|STATE ROAD DEPT|^FLORIDA DEP(T|ARTMENT) OF|\bTIIT?F\b|\bTRS? (OF )?(THE )?I ?I (TRUST )?FUND|TRS OF THE INTERNAL|INTERNAL IMPROVEMENT|\bFDOT\b|DEP(T|ARTMENT) OF TRANSPORTATION|BOARD OF TRUSTEES OF THE|UNIVERSITY BOARD|BOARD OF REGENTS"),
    ("district", r"\bCOMMUNITY$|COMMUNITY REDEV|WATER CONTR|INLAND NAVIGATION|CONSERVANCY DIST|\bCDD\b|INLET DIST|IMPROVEMENT$|\bDRAINAGE\b|BEACH (&|AND) PAR|SOUTHEAST OVERTOWN|OMNI (CRA|REDEV)|WATER (MANAGEMENT|MGMT|MGT)|(SOUTH|SO) (FLA|FLORIDA|FL) WATER|\bSFWMD\b|HOUSING AUTH|REDEVELOPMENT (AGENCY|AGY|AUTH)|COMMUNITY REDEVELOP|\bC ?R ?A$|\bCRA\b|DRAINAGE DIST|EXPRESSWAY|PORT (OF|AUTHORITY)|AIRPORT AUTH|TRANSPORTATION AUTH|HOSPITAL DIST|HEALTH CARE DIST|IMPROVEMENT DIST"),
    ("municipal", r"\b(CITY|TOWN|VILLAGE) OF\b|OFF[- ]ST(REET)? PARKING|\bVILLAGE$"),
    ("county", r"^(MIAMI[- ]DADE|BROWARD|PALM BEACH)( COUNTY)?( (AVIATION|TRANSIT|HOUSING|PARKS?|WATER|PUBLIC|FIRE|POLICE|SEAPORT|LIBRARY|DERM|GSA|ISD)|$)|PUBLIC HOUSING (&|AND) COMM|WATER (&|AND) SEWER|PARKS? (&|AND) REC|AVIATION DEP|SOLID WASTE|PUBLIC WORKS DEP|PUBLIC HEALTH TRUST|AFFORDABLE HOUSING (&|AND) COMM"),
    ("county", r"\bCOUNTY\b"),
]
_RULES = [(lvl, re.compile(rx)) for lvl, rx in OWNER_RULES]
# Tax-roll public-land flag. Only the unambiguous letters are trusted; in practice "D" is
# set on parcels of every level, so it only tells us the parcel is public, not whose it is.
PUBLIC_LND = {"F": "federal", "S": "state", "T": "state", "C": "county", "M": "municipal", "W": "district", "D": "other", "R": "other"}
# Names that contain a government-sounding phrase but are private ("REAL ESTATE OF FL LLC",
# "UNITED STATES DEVELOPMENT LTD", "LONGSHOREMEN OF DADE COUNTY INC").
PRIVATE = re.compile(r"\b(LLC|L L C|INC|LTD|CORP(?! OF ENG)|LLP|LP|ASSOC|ASSN|FOUNDATION|PARTNERS|PARTNERSHIP|HOLDINGS|INVESTMENTS|CHURCH|CLUB)\b|\bCONDO|\b(ASSOC|INVESTMENTS|LONGSHOREMEN|BANK) (FOR|OF)\b")

ZONE_WORDS = [("mixed-use", ("urban center", "urban area district", "corridor district", "mixed use", "traditional neighborhood")),
              ("multifamily", ("apartment", "multi-family", "multifamily", "multiple family")),
              ("residential", ("townhouse", "two-family", "duplex", "bungalow")),
              ("single-family", ("single-family", "single family", "estate")),
              ("commercial", ("business", "office", "commercial", "retail")),
              ("industrial", ("industrial", "employment center", "manufactur")),
              ("agricultural", ("agricultur",))]
DENSITY_RX = re.compile(r"(\d+(?:\.\d+)?)\s*(?:dwelling\s+)?units?\s*(?:/|per)\s*(?:net\s+|gross\s+)?acre", re.I)


def zoning_from_description(desc):
    """Category and density as far as the zoning layer's own description states them."""
    d = (desc or "").replace("\xa0", " ").lower()
    if not d.strip():
        return None, None
    cat = next((c for c, words in ZONE_WORDS if any(w in d for w in words)), "other")
    m = DENSITY_RX.search(d)
    return cat, (float(m.group(1)) if m else None)
USE_LEVEL = {81: "federal", 83: "school", 86: "county", 87: "state", 88: "federal", 89: "municipal"}


def owner_level(owner, use_code=None, public_flag=None, county_patterns=()):
    """Return (level, how_we_know) or (None, None) if nothing says it is government."""
    name = (owner or "").upper()
    coded = use_code is not None and 80 <= use_code <= 89
    if PRIVATE.search(name) and not re.search(r"HOUSING AUTH|REDEVELOP", name):
        return ("other", "land use code") if coded else (None, None)
    for p in county_patterns:
        if p.upper() in name:
            return "county", "owner name"
    for lvl, rx in _RULES:
        if rx.search(name):
            return lvl, "owner name"
    if public_flag and public_flag.upper() in PUBLIC_LND:
        return PUBLIC_LND[public_flag.upper()], "tax roll public-land flag"
    if use_code in USE_LEVEL:
        return USE_LEVEL[use_code], "land use code"
    if use_code is not None and 80 <= use_code <= 90:
        return "other", "land use code"
    return None, None


DEPT_RX = re.compile(r"DEP(T|ARTMENT)\b|DIVISION|\bDIV\b|PARKS?\b|RECREATION|WATER|SEWER|AVIATION|TRANSIT|HOUSING|PUBLIC WORKS|"
                     r"SEAPORT|LIBRAR|FIRE|POLICE|REAL ESTATE|ASSET M|FACILIT|INTERNAL SERV|\bISD\b|\bGSA\b|\bDERM\b|"
                     r"\bWASD\b|\bPHCD\b|\bCRA\b|REDEVELOP|SCHOOL|PLANNING|ECONOMIC|TRANSPORTATION|RIGHT OF WAY|R/W")


def department_of(line2, owner=""):
    """The holding department, when the tax roll puts it on the owner's first address line
    ("MIAMI-DADE COUNTY" / "WATER AND SEWER DEPT") or after a slash or dash in the name."""
    s = (line2 or "").strip().upper()
    if s and not re.match(r"^(\d|P ?O ?BOX|C/O|%|ATTN)", s) and DEPT_RX.search(s):
        return s.title()
    m = re.search(r"[/%-]\s*(.+)$", (owner or "").upper())
    if m and DEPT_RX.search(m.group(1)):
        return m.group(1).strip().title()
    return None


def load_table(path, key_fields):
    out = {}
    if path and os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                out[tuple((row.get(k) or "").strip().upper() for k in key_fields)] = row
    return out


def enrich(rec, county_cfg, density, surplus):
    """Turn a provider record into an app record. Returns None if not government."""
    lvl, basis = owner_level(rec["owner"], rec["use_code"], rec["public_land_flag"],
                             county_cfg.get("owner_patterns", ()))
    if not lvl or not rec["id"]:
        return None
    uc = rec["use_code"]
    jv, lv = rec["just_value"] or 0, rec["land_value"] or 0
    if rec["buildings"] is None:
        vacant = None
    else:
        vacant = rec["buildings"] == 0 and (uc == 80 or jv - lv <= max(0.05 * jv, 10000))
    out = dict(rec)
    out["department"] = department_of(rec.get("owner_line2"), rec["owner"])
    out.update(owner_level=lvl, gov_basis=basis, vacant=vacant,
               use_label=USE_LABELS.get(uc, "Non-governmental use code %s" % uc if uc is not None else "Unknown"),
               leased=(uc == 90), coded_gov=uc is not None and 80 <= uc <= 89)
    zc = (rec["zoning"] or "").upper().strip()
    jur = (rec.get("zoning_jurisdiction") or "").upper()
    # exact code first, then progressively broader: "T6-8-O" -> "T6-8" -> "T6", then the layer's own group field
    parts = zc.split("-")
    tries = [zc] + ["-".join(parts[:n]) for n in range(len(parts) - 1, 0, -1)] + [(rec.get("zoning_group") or "").upper().strip()]
    z = next((density[k] for t in tries if t for k in ((jur, t), (rec["county"].upper(), t)) if k in density), None)
    out["max_du_per_acre_high"] = out["density_note"] = None
    if z:      # the hand-checked table wins over what the layer description implied
        out["zoning_category"] = z.get("category") or out["zoning_category"]
        for src, dst in (("max_du_per_acre", "max_du_per_acre"), ("max_du_per_acre_high", "max_du_per_acre_high")):
            try:
                out[dst] = float(z[src])
            except (KeyError, ValueError, TypeError):
                pass
        out["density_note"] = (z.get("note") or "").strip() or None
    d, ac = out["max_du_per_acre"], out["acres"]
    out["est_units"] = int(d * ac) if d and ac else None
    s = surplus.get((rec["county"].upper(), rec["id"].upper()))
    out["surplus_list"] = s.get("list_name") if s else None
    out["appraiser_url"] = county_cfg.get("appraiser_url", "").replace("{id}", rec["id"].replace("-", "")) or None
    return out


WATCHED = [("owner", "Owner changed"), ("use_code", "Use code changed"),
           ("zoning", "Zoning changed"), ("surplus_list", "Surplus status changed"),
           ("vacant", "Vacant status changed")]


def diff(old, new, today, failed_counties=()):
    """Compare two {key: record} maps. A county whose fetch failed is skipped so an
    outage is never reported as parcels leaving government hands."""
    changes = []
    seen_before = {o["county"] for o in old.values()}      # a county's first load is not a list of "new" parcels
    for k, r in new.items():
        o = old.get(k)
        if o is None:
            r["first_seen"] = today
            if r["county"] in seen_before:
                changes.append(dict(date=today, type="added", id=r["id"], county=r["county"],
                                    detail="New government parcel: %s" % r["owner"]))
            continue
        r["first_seen"] = o.get("first_seen", today)
        for f, label in WATCHED:
            if o.get(f) != r.get(f):
                changes.append(dict(date=today, type="changed", id=r["id"], county=r["county"],
                                    detail="%s: %s -> %s" % (label, o.get(f), r.get(f))))
    for k, o in old.items():
        if k not in new and o["county"] not in failed_counties:
            changes.append(dict(date=today, type="removed", id=o["id"], county=o["county"],
                                detail="No longer government-owned or parcel retired (was %s)" % o["owner"]))
    return changes


def zoning_lookup(lat, lon, sources, stats=None):
    """Ask each enabled zoning layer which zone contains this point. Returns
    (jurisdiction, code, description, group) from the first layer that covers it, else None.
    A layer that errors is skipped for the rest of the run so one dead server
    cannot stall the refresh."""
    for s in sources:
        if not (s.get("enabled") and s.get("url") and s.get("code_field")) or s.get("_dead"):
            continue
        fields = ",".join(f for f in (s["code_field"], s.get("desc_field"), s.get("group_field")) if f)
        try:
            d = providers._get_json(s["url"].rstrip("/") + "/query", {
                "geometry": "%s,%s" % (lon, lat), "geometryType": "esriGeometryPoint", "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects", "outFields": fields,
                "returnGeometry": "false", "f": "json"}, retries=2, timeout=30)
        except Exception as e:
            s["_dead"] = str(e)
            continue
        feats = d.get("features") or []
        if feats:
            a = {k.lower(): v for k, v in feats[0]["attributes"].items()}
            code = a.get(s["code_field"].lower())
            if code not in (None, ""):
                grp = a.get((s.get("group_field") or "").lower())
                return (s["jurisdiction"], str(code).strip(), (a.get((s.get("desc_field") or "").lower()) or None),
                        str(grp).strip() if grp not in (None, "") else None)
    return None


def _in_ring(x, y, ring):
    inside, n = False, len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


class Boundary:
    """A development boundary (e.g. Miami-Dade's UDB) as lon/lat polygons, with a point test."""
    def __init__(self, geojson, name=""):
        self.name, self.polys = name, []
        for f in geojson["features"]:
            g = f["geometry"]
            self.polys += [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        if not self.polys:
            raise ValueError("boundary has no polygons")

    def contains(self, lon, lat):
        if lon is None or lat is None:
            return None
        for poly in self.polys:          # inside the outer ring and not inside a hole
            if _in_ring(lon, lat, poly[0]) and not any(_in_ring(lon, lat, h) for h in poly[1:]):
                return True
        return False


def load_boundary(bcfg, base):
    """Fresh copy from the county's server if reachable, else the saved file."""
    if not bcfg:
        return None
    path = os.path.join(base, bcfg["file"])
    if bcfg.get("url"):
        try:
            d = providers._get_json(bcfg["url"].rstrip("/") + "/query", {"where": "1=1", "outFields": "OBJECTID", "outSR": 4326,
                                    "f": "geojson", "geometryPrecision": 5, "maxAllowableOffset": 0.0001}, retries=2, timeout=60)
            b = Boundary(d, bcfg.get("name", ""))
            json.dump(d, open(path, "w"), separators=(",", ":"))
            return b
        except Exception as e:
            print("   boundary server unavailable, using saved copy (%s)" % str(e)[:100])
    return Boundary(json.load(open(path)), bcfg.get("name", ""))
