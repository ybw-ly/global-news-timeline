#!/usr/bin/env python3
"""Build runtime country metadata and the inline SVG world map.

Source: Natural Earth 1:110m admin-0 countries (public domain).
Run:
    uv run --with babel python scripts/build_assets.py
Babel is only needed to generate Chinese country names; the app runtime has
zero third-party dependencies and reads the generated config/countries.json.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "data" / "geo" / "countries.geojson"
CONFIG = ROOT / "config"
WEB = ROOT / "web"

W = 1000.0
LAT_TOP = 84.0
LAT_BOTTOM = -58.0
H = round(W * (LAT_TOP - LAT_BOTTOM) / 360.0, 1)

MIDDLE_EAST = {
    "BH", "AE", "QA", "KW", "OM", "SA", "YE", "IL", "PS", "JO",
    "LB", "SY", "IQ", "IR", "TR", "EG",
}

REGION_BY_SUBREGION = {
    "Northern America": "north_america",
    "Central America": "latin_america",
    "Caribbean": "latin_america",
    "South America": "latin_america",
    "Europe": "europe",
    "Eastern Europe": "europe",
    "Northern Europe": "europe",
    "Southern Europe": "europe",
    "Western Europe": "europe",
    "Western Asia": "middle_east",
    "Northern Africa": "africa",
    "Eastern Africa": "africa",
    "Middle Africa": "africa",
    "Southern Africa": "africa",
    "Western Africa": "africa",
    "Southern Asia": "south_asia",
    "Eastern Asia": "east_asia",
    "South-Eastern Asia": "southeast_asia",
    "Central Asia": "central_asia",
    "Australia and New Zealand": "oceania",
    "Melanesia": "oceania",
    "Micronesia": "oceania",
    "Polynesia": "oceania",
}

NAME_ZH_OVERRIDES = {
    "TW": "中国台湾",
    "HK": "中国香港",
    "MO": "中国澳门",
    "PS": "巴勒斯坦",
    "KR": "韩国",
    "KP": "朝鲜",
    "CD": "刚果（金）",
    "CG": "刚果（布）",
    "CI": "科特迪瓦",
    "CZ": "捷克",
    "MK": "北马其顿",
    "SZ": "斯威士兰",
    "TL": "东帝汶",
    "VA": "梵蒂冈",
}


def project(lon: float, lat: float) -> tuple[float, float]:
    x = (lon + 180.0) / 360.0 * W
    y = (LAT_TOP - lat) / (LAT_TOP - LAT_BOTTOM) * H
    return round(x, 1), round(y, 1)


def ring_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def path_for_polygon(polygon: list[list[list[float]]]) -> str:
    parts: list[str] = []
    for ring in polygon:
        if len(ring) < 3:
            continue
        # Unwrap longitudes across the antimeridian so a ring does not draw a
        # horizontal line across the entire map. Off-screen points are clipped
        # by the SVG viewBox.
        unwrapped: list[tuple[float, float]] = []
        offset = 0.0
        prev_lon: float | None = None
        for pair in ring:
            lon, lat = float(pair[0]), float(pair[1])
            if prev_lon is not None:
                delta = lon - prev_lon
                if delta > 180:
                    offset -= 360.0
                elif delta < -180:
                    offset += 360.0
            unwrapped.append((lon + offset, lat))
            prev_lon = lon

        projected = [project(lon, lat) for lon, lat in unwrapped]

        # Light simplification: drop points that are nearly identical.
        clean: list[tuple[float, float]] = []
        for p in projected:
            if not clean or abs(p[0] - clean[-1][0]) + abs(p[1] - clean[-1][1]) > 0.35:
                clean.append(p)
        if len(clean) < 3 or ring_area(clean) < 2.0:
            continue
        if max(x for x, _ in clean) < -20 or min(x for x, _ in clean) > W + 20:
            continue

        d = [f"M{clean[0][0]:.1f},{clean[0][1]:.1f}"]
        d.extend(f"L{x:.1f},{y:.1f}" for x, y in clean[1:])
        d.append("Z")
        parts.append("".join(d))
    return "".join(parts)


def load_chinese_names() -> dict[str, str]:
    try:
        from babel import Locale  # type: ignore

        return dict(Locale("zh").territories)
    except Exception:
        return {}


def main() -> None:
    data = json.loads(GEO.read_text(encoding="utf-8"))
    zh_names = load_chinese_names()
    countries: dict[str, dict] = {}
    map_countries: list[dict] = []

    for feature in data["features"]:
        props = feature.get("properties", {})
        iso2 = props.get("ISO_A2_EH") or props.get("ISO_A2")
        if not iso2 or iso2 in ("-99", "-1"):
            continue
        continent = props.get("CONTINENT") or ""
        subregion = props.get("SUBREGION") or ""
        if continent in ("Antarctica", "Seven seas (open ocean)"):
            continue

        region = REGION_BY_SUBREGION.get(subregion, "other")
        if iso2 in MIDDLE_EAST:
            region = "middle_east"
        if iso2 == "MX":
            region = "latin_america"

        name_en = props.get("NAME") or props.get("ADMIN") or iso2
        name_zh = NAME_ZH_OVERRIDES.get(iso2) or zh_names.get(iso2) or name_en

        lat = props.get("LABEL_Y")
        lon = props.get("LABEL_X")
        if lat is None or lon is None:
            # Fallback: average of the outer ring.
            rings = []
            geom = feature.get("geometry", {})
            if geom.get("type") == "Polygon":
                rings = [geom["coordinates"][0]]
            elif geom.get("type") == "MultiPolygon":
                rings = [p[0] for p in geom["coordinates"]]
            pts = [pt for ring in rings for pt in ring]
            lon = sum(p[0] for p in pts) / max(len(pts), 1)
            lat = sum(p[1] for p in pts) / max(len(pts), 1)

        x, y = project(float(lon), float(lat))
        x = min(max(x, 2.0), W - 2.0)
        y = min(max(y, 2.0), H - 2.0)

        geom = feature.get("geometry", {})
        polygons = []
        if geom.get("type") == "Polygon":
            polygons = [geom["coordinates"]]
        elif geom.get("type") == "MultiPolygon":
            polygons = geom["coordinates"]

        d = "".join(path_for_polygon(poly) for poly in polygons)
        if not d:
            continue

        countries[iso2] = {
            "name_en": name_en,
            "name_zh": name_zh,
            "region": region,
            "lat": round(float(lat), 3),
            "lon": round(float(lon), 3),
        }
        map_countries.append(
            {
                "id": iso2,
                "name": name_en,
                "nameZh": name_zh,
                "region": region,
                "x": x,
                "y": y,
                "d": d,
            }
        )

    # Natural Earth's 110m file omits small city economies that matter as
    # news-source locations. Add marker-only entries for them.
    manual = {
        "HK": ("Hong Kong", "中国香港", "east_asia", 22.32, 114.17),
        "MO": ("Macao", "中国澳门", "east_asia", 22.20, 113.54),
        "SG": ("Singapore", "新加坡", "southeast_asia", 1.35, 103.82),
    }
    for iso2, (name_en, name_zh, region, lat, lon) in manual.items():
        if iso2 in countries:
            continue
        x, y = project(lon, lat)
        d = (
            f"M{x:.1f},{y - 3.2:.1f}L{x + 3.2:.1f},{y:.1f}"
            f"L{x:.1f},{y + 3.2:.1f}L{x - 3.2:.1f},{y:.1f}Z"
        )
        countries[iso2] = {
            "name_en": name_en,
            "name_zh": name_zh,
            "region": region,
            "lat": lat,
            "lon": lon,
        }
        map_countries.append(
            {
                "id": iso2,
                "name": name_en,
                "nameZh": name_zh,
                "region": region,
                "x": round(x, 1),
                "y": round(y, 1),
                "d": d,
            }
        )

    map_countries.sort(key=lambda c: c["id"])
    CONFIG.mkdir(parents=True, exist_ok=True)
    WEB.mkdir(parents=True, exist_ok=True)
    (CONFIG / "countries.json").write_text(
        json.dumps(countries, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )

    payload = {"width": W, "height": H, "countries": map_countries}
    js = "window.WORLD_MAP=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (WEB / "world-map.js").write_text(js, encoding="utf-8")

    total_kb = len(js.encode("utf-8")) / 1024
    print(f"countries: {len(countries)}  map: {total_kb:.1f} KB  viewBox: 0 0 {W:g} {H:g}")


if __name__ == "__main__":
    main()
