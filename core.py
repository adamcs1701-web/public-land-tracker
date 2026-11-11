"""Source-independent logic: who owns it, what it is, and what changed."""
import csv, os, re
import providers

USE_LABELS = {80: "Vacant governmental", 81: "Military", 82: "Forest, park, recreation",
              83: "Public school", 84: "College", 85: "Hospital", 86: "County (other)",
              87: "State (other)", 88: "Federal (other)", 89: "Municipal (other)",
              90: "Government land leased to private party"}

# First match wins, so order matters (school boards before counties, etc.).
OWNER_RULES = [
    ("school", r"SCHOOL (BOARD|DISTRICT)|BOARD OF PUBLIC INSTRUCTION|\bSBBC\b"),
    ("federal", r"UNITED STATES|\bU ?S ?A\b|\bU S GOVERNMENT|US DEPT|FEDERAL AVIATION|POSTAL SERVICE"),
    ("state", r"STATE OF FL|\bTIITF\b|INTERNAL IMPROVEMENT|\bFDOT\b|DEP(T|ARTMENT) OF TRANSPORTATION|BOARD OF TRUSTEES OF THE|UNIVERSITY BOARD|BOARD OF REGENTS"),
    ("district", r"WATER MANAGEMENT|\bSFWMD\b|HOUSING AUTH|REDEVELOPMENT AGENCY|\bCRA\b|DRAINAGE DIST|EXPRESSWAY|PORT (OF|AUTHORITY)|AIRPORT AUTH|TRANSPORTATION AUTH|HOSPITAL DIST|HEALTH CARE DIST|IMPROVEMENT DIST"),
    ("municipal", r"\b(CITY|TOWN|VILLAGE) OF\b"),
    ("county", r"\bCOUNTY\b"),
]
_RULES = [(lvl, re.compile(rx)) for lvl, rx in OWNER_RULES]
PUBLIC_LND = {"F": "federal", "S": "state", "C": "county", "M": "municipal", "D": "district"}
USE_LEVEL = {81: "federal", 83: "school", 86: "county", 87: "state", 88: "federal", 89: "municipal"}


def owner_level(owner, use_code=None, public_flag=None, county_patterns=()):
    """Return (level, how_we_know) or (None, None) if nothing says it is government."""
    name = (owner or "").upper()
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
    out.update(owner_level=lvl, gov_basis=basis, vacant=vacant,
               use_label=USE_LABELS.get(uc, "Non-governmental use code %s" % uc if uc is not None else "Unknown"),
               leased=(uc == 90), coded_gov=uc is not None and 80 <= uc <= 89)
    zc = (rec["zoning"] or "").upper()
    z = density.get(((rec.get("zoning_jurisdiction") or "").upper(), zc)) or density.get((rec["county"].upper(), zc))
    if z:
        out["zoning_category"] = out["zoning_category"] or z.get("category") or None
        try:
            out["max_du_per_acre"] = float(z["max_du_per_acre"])
        except (KeyError, ValueError, TypeError):
            pass
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
    for k, r in new.items():
        o = old.get(k)
        if o is None:
            r["first_seen"] = today
            if old:
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
    (jurisdiction, code, description) from the first layer that covers it, else None.
    A layer that errors is skipped for the rest of the run so one dead server
    cannot stall the refresh."""
    for s in sources:
        if not (s.get("enabled") and s.get("url") and s.get("code_field")) or s.get("_dead"):
            continue
        fields = s["code_field"] + ("," + s["desc_field"] if s.get("desc_field") else "")
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
                return s["jurisdiction"], str(code).strip(), (a.get((s.get("desc_field") or "").lower()) or None)
    return None
