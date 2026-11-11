"""Data-source adapters. Every provider returns the same normalized parcel dict,
so the rest of the pipeline never knows (or cares) where a record came from.

To add a source: subclass Provider, implement fetch(), register it in PROVIDERS.
"""
import csv, json, os, time, urllib.parse, urllib.request

GOV_USE_CODES = range(80, 90)          # DOR land use codes 80-89 = governmental
LEASEHOLD_CODE = 90                    # gov-owned land leased to a private party

# Normalized record: the contract between providers and everything downstream.
FIELDS = ["id", "county", "owner", "use_code", "acres", "buildings", "just_value",
          "land_value", "address", "city", "lat", "lon", "public_land_flag",
          "zoning", "zoning_category", "max_du_per_acre", "flood_zone", "roll_year",
          "zoning_jurisdiction", "zoning_description"]


def blank():
    return {f: None for f in FIELDS}


class Provider:
    def __init__(self, cfg, county_key, county_cfg):
        self.cfg, self.county_key, self.county = cfg, county_key, county_cfg
        self.name = cfg.get("name", cfg["type"])

    def fetch(self):
        """Yield normalized dicts for candidate government parcels in this county."""
        raise NotImplementedError

    def as_of(self):
        """ISO date the source says it was last updated, or None if unknown."""
        return None


def _get_json(url, params=None, retries=3, timeout=90):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "govland-tracker/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            if isinstance(data, dict) and "error" in data:
                raise RuntimeError("ArcGIS error: %s" % data["error"])
            return data
        except Exception as e:      # retry transient failures with backoff
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("request failed after %d tries: %s (%s)" % (retries, url[:200], last))


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _ring_centroid(geom):
    pts = [p for ring in (geom or {}).get("rings", []) for p in ring]
    if not pts:
        return None, None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


class ArcGISDorProvider(Provider):
    """Any ArcGIS feature layer published in the Florida DOR tax-roll (NAL) schema:
    the statewide cadastral layer, or a county layer that keeps the DOR field names.
    Two passes: (1) parcels coded governmental, (2) parcels whose owner name looks
    governmental but were coded something else."""
    OUT = ("PARCEL_ID,CO_NO,OWN_NAME,DOR_UC,LND_SQFOOT,NO_BULDNG,JV,LND_VAL,"
           "PHY_ADDR1,PHY_CITY,PUBLIC_LND,ASMNT_YR")
    # Server-side net for government owners whose parcels are NOT coded 80-89.
    # Deliberately loose: core.owner_level() makes the final call on each row.
    NAME_TERMS = ["UNITED STATES", "STATE OF FL", "TIITF", "INTERNAL IMPROVEMENT", "CITY OF ", "TOWN OF ",
                  "VILLAGE OF ", "SCHOOL BOARD", "SCHOOL DIST", "PUBLIC INSTRUCTION", "HOUSING AUTH",
                  "WATER MANAGEMENT", "SFWMD", "REDEVELOPMENT", " CRA", "DEPT OF TRANSPORTATION",
                  "DEPARTMENT OF TRANSPORTATION", "FDOT", "EXPRESSWAY", "TRANSPORTATION AUTH",
                  "HOSPITAL DIST", "HEALTH CARE DIST", "DRAINAGE DIST", "IMPROVEMENT DIST",
                  "PORT AUTH", "AIRPORT AUTH"]

    def __init__(self, *a):
        super().__init__(*a)
        self.url = self.cfg["url"].rstrip("/")
        self._meta = None

    def meta(self):
        if self._meta is None:
            self._meta = _get_json(self.url, {"f": "json"})
        return self._meta

    def as_of(self):
        ms = (self.meta().get("editingInfo") or {}).get("dataLastEditDate")
        return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000)) if ms else None

    def _field_type(self, name):
        for f in self.meta().get("fields", []):
            if f["name"].upper() == name:
                return f.get("type", "")
        return ""

    WINDOW = 100000

    def _clauses(self):
        codes = list(GOV_USE_CODES) + [LEASEHOLD_CODE]
        if "String" in self._field_type("DOR_UC"):
            vals = ",".join("'%03d','%02d'" % (c, c) for c in codes)
        else:
            vals = ",".join(str(c) for c in codes)
        yield "DOR_UC IN (%s)" % vals
        terms = self.NAME_TERMS + self.county.get("owner_patterns", [])
        likes = " OR ".join("OWN_NAME LIKE '%%%s%%'" % t.replace("'", "''") for t in terms)
        yield "DOR_UC NOT IN (%s) AND (%s)" % (vals, likes)

    def _co_sql(self):
        co = self.county["dor_county_no"]
        return "CO_NO=%s" % ("'%s'" % co if "String" in self._field_type("CO_NO") else co)

    def _oid_span(self):
        """The statewide layer times out on plain county filters but answers instantly
        when a query is bounded by OBJECTID, so find the county's OBJECTID span first."""
        stats = json.dumps([{"statisticType": s, "onStatisticField": "OBJECTID", "outStatisticFieldName": n}
                            for s, n in (("min", "lo"), ("max", "hi"))])
        d = _get_json(self.url + "/query", {"where": self._co_sql(), "outStatistics": stats, "f": "json"})
        a = {k.lower(): v for k, v in d["features"][0]["attributes"].items()}
        if a.get("lo") is None:
            raise RuntimeError("no parcels found for county number %s" % self.county["dor_county_no"])
        return int(a["lo"]), int(a["hi"])

    def _window(self, lo, hi, clause):
        """Fetch one OBJECTID window; if the server truncates or rejects it, split it in half."""
        where = "OBJECTID BETWEEN %d AND %d AND %s AND %s" % (lo, hi, self._co_sql(), clause)
        try:
            data = _get_json(self.url + "/query", {
                "where": where, "outFields": self.OUT, "returnGeometry": "false",
                "returnCentroid": "true", "outSR": 4326, "f": "json"}, timeout=150)
        except RuntimeError:
            if hi - lo < 2000:
                raise
            data = None
        if data is not None and not data.get("exceededTransferLimit"):
            for ft in data.get("features", []):
                yield self._normalize(ft)
            return
        if hi <= lo:
            raise RuntimeError("single OBJECTID %d still truncated" % lo)
        mid = (lo + hi) // 2
        yield from self._window(lo, mid, clause)
        yield from self._window(mid + 1, hi, clause)

    def fetch(self):
        lo, hi = self._oid_span()
        for clause in self._clauses():
            for start in range(lo, hi + 1, self.WINDOW):
                yield from self._window(start, min(start + self.WINDOW - 1, hi), clause)

    def _normalize(self, ft):
        a = {k.upper(): v for k, v in ft["attributes"].items()}
        c = ft.get("centroid") or {}
        lon, lat = c.get("x"), c.get("y")
        if lon is None:
            lon, lat = _ring_centroid(ft.get("geometry"))
        r = blank()
        sqft = _num(a.get("LND_SQFOOT"))
        r.update(id=str(a.get("PARCEL_ID") or "").strip(), county=self.county_key,
                 owner=(a.get("OWN_NAME") or "").strip(),
                 use_code=int(_num(a.get("DOR_UC")) or 0) if _num(a.get("DOR_UC")) is not None else None,
                 acres=round(sqft / 43560, 3) if sqft else None,
                 buildings=int(_num(a.get("NO_BULDNG")) or 0),
                 just_value=_num(a.get("JV")), land_value=_num(a.get("LND_VAL")),
                 address=(a.get("PHY_ADDR1") or "").strip(), city=(a.get("PHY_CITY") or "").strip(),
                 lat=lat, lon=lon, public_land_flag=(a.get("PUBLIC_LND") or "").strip() or None,
                 roll_year=a.get("ASMNT_YR"))
        return r


# Regrid column -> normalized field. Check against Regrid's current schema page before
# first use (https://support.regrid.com/parcel-data/schema); names are from their
# standard schema and have not been run against a live licensed file.
REGRID_MAP = {"parcelnumb": "id", "owner": "owner", "ll_gisacre": "acres",
              "parval": "just_value", "landval": "land_value", "address": "address",
              "scity": "city", "lat": "lat", "lon": "lon", "zoning": "zoning",
              "zoning_type": "zoning_category", "fema_flood_zone": "flood_zone",
              "struct": "_struct", "usecode": "_usecode", "taxyear": "roll_year"}


def _regrid_row(row, county_key):
    r = blank()
    for src, dst in REGRID_MAP.items():
        if src in row and not dst.startswith("_"):
            r[dst] = row[src]
    for k in ("acres", "just_value", "land_value", "lat", "lon"):
        r[k] = _num(r[k])
    r["id"] = str(r["id"] or "").strip()
    r["county"] = county_key
    uc = _num(row.get("usecode"))
    r["use_code"] = int(uc) if uc is not None else None
    s = str(row.get("struct", "")).strip().lower()
    r["buildings"] = 1 if s in ("true", "t", "1", "yes") else 0 if s in ("false", "f", "0", "no") else None
    return r


class RegridFileProvider(Provider):
    """Reads a Regrid county bulk export (CSV). Keeps every row: the government
    filter runs downstream on owner name + use code, same as for free sources."""
    def fetch(self):
        with open(self.cfg["path"], newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                yield _regrid_row({k.lower(): v for k, v in row.items()}, self.county_key)

    def as_of(self):
        return time.strftime("%Y-%m-%d", time.gmtime(os.path.getmtime(self.cfg["path"])))


class RegridApiProvider(Provider):
    """Regrid Parcel API v2. Needs a token in the env var named by token_env.
    Not exercised in the proof of concept (no licence); confirm endpoint and
    paging against https://support.regrid.com/api/parcel-api-endpoints first."""
    BASE = "https://app.regrid.com/api/v2/parcels/query"

    def fetch(self):
        token = os.environ.get(self.cfg.get("token_env", "REGRID_TOKEN"))
        if not token:
            raise RuntimeError("Regrid token missing: set %s" % self.cfg.get("token_env", "REGRID_TOKEN"))
        terms = ArcGISDorProvider.NAME_TERMS + self.county.get("owner_patterns", [])
        for term in terms:
            offset = 0
            while True:
                data = _get_json(self.BASE, {"token": token, "path": self.cfg["county_path"],
                                             "fields[owner][ilike]": "%" + term.strip() + "%",
                                             "limit": 1000, "offset": offset, "return_geometry": "false"})
                feats = (data.get("parcels") or data).get("features", [])
                for ft in feats:
                    props = ft.get("properties", {})
                    yield _regrid_row({k.lower(): v for k, v in (props.get("fields") or props).items()}, self.county_key)
                if len(feats) < 1000:
                    break
                offset += len(feats)

    def as_of(self):
        return time.strftime("%Y-%m-%d")


PROVIDERS = {"arcgis_dor": ArcGISDorProvider, "regrid_file": RegridFileProvider,
             "regrid_api": RegridApiProvider}


def make(cfg, county_key, county_cfg):
    return PROVIDERS[cfg["type"]](cfg, county_key, county_cfg)
