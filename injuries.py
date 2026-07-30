"""Gedeelde blessure-informatie voor alle AI-coaches.

Blessures worden centraal opgeslagen in `health_input.json` in de Gist, onder de
sleutel `injuries`. Alle AI-coaches (WOD-uitvoeringsplan, herstel-advies,
Open Gym, thuistraining, hardloopplan en de hardloop-review) lezen dezelfde
lijst, zodat één invoer in de PWA overal doorwerkt.

Formaat in health_input.json:

    "injuries": [
      {
        "id": "1722345678901",
        "area": "linkerschouder",
        "description": "pijn bij overhead druk",
        "severity": "matig",            // licht | matig | ernstig
        "status": "actief",             // actief | herstellend | hersteld
        "since": "2026-07-20",
        "avoid": ["overhead press", "snatch"],
        "notes": "fysio adviseert geen belasting boven schouderhoogte"
      }
    ]

Alleen `area` is verplicht. Voor snelle handmatige invoer wordt ook vrije tekst
geaccepteerd (`"injuries": "linkerschouder pijn bij overhead"`) of een lijst met
strings. Blessures met status `hersteld` blijven in het bestand staan als
historie, maar worden niet meer aan de coaches meegegeven.
"""
from __future__ import annotations

VALID_SEVERITIES = ("licht", "matig", "ernstig")
VALID_STATUSES = ("actief", "herstellend", "hersteld")

# Statussen die als "hersteld" tellen (NL + EN, voor handmatige invoer in de Gist)
_RESOLVED = {"hersteld", "resolved", "genezen", "afgerond", "klaar", "healed"}

_SEVERITY_LABEL_NL = {
    "licht": "licht",
    "matig": "matig",
    "ernstig": "ernstig",
}
_SEVERITY_LABEL_EN = {
    "licht": "mild",
    "matig": "moderate",
    "ernstig": "severe",
}
_STATUS_LABEL_EN = {
    "actief": "active",
    "herstellend": "recovering",
    "hersteld": "resolved",
}


def _clean(value) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _normalise_entry(raw) -> dict | None:
    """Zet één ruwe entry om naar een genormaliseerde blessure-dict."""
    if isinstance(raw, str):
        area = _clean(raw)
        return {"area": area, "description": "", "severity": "", "status": "actief",
                "since": "", "avoid": [], "notes": ""} if area else None

    if not isinstance(raw, dict):
        return None

    area = _clean(raw.get("area") or raw.get("locatie") or raw.get("body_part") or raw.get("name"))
    description = _clean(raw.get("description") or raw.get("omschrijving") or raw.get("klacht"))
    if not area and not description:
        return None

    severity = _clean(raw.get("severity") or raw.get("ernst")).lower()
    if severity not in VALID_SEVERITIES:
        severity = ""

    status = _clean(raw.get("status")).lower()
    if status in _RESOLVED:
        status = "hersteld"
    elif status not in VALID_STATUSES:
        status = "actief"

    avoid_raw = raw.get("avoid") or raw.get("vermijden") or []
    if isinstance(avoid_raw, str):
        avoid = [p.strip() for p in avoid_raw.replace(";", ",").split(",") if p.strip()]
    elif isinstance(avoid_raw, (list, tuple)):
        avoid = [_clean(p) for p in avoid_raw if _clean(p)]
    else:
        avoid = []

    return {
        "id": _clean(raw.get("id")),
        "area": area or description,
        "description": description if area else "",
        "severity": severity,
        "status": status,
        "since": _clean(raw.get("since") or raw.get("sinds")),
        "avoid": avoid,
        "notes": _clean(raw.get("notes") or raw.get("notitie") or raw.get("opmerking")),
    }


def parse_injuries(health_input: dict | None, include_resolved: bool = False) -> list[dict]:
    """Lees en normaliseer het `injuries`-veld uit health_input.json.

    Accepteert een lijst met dicts, een lijst met strings of één vrije-tekstregel
    (gescheiden door `;` of nieuwe regels). Herstelde blessures worden standaard
    weggefilterd.
    """
    if not isinstance(health_input, dict):
        return []

    raw = health_input.get("injuries")
    if not raw:
        return []

    if isinstance(raw, str):
        items: list = [p.strip() for p in raw.replace("\n", ";").split(";") if p.strip()]
    elif isinstance(raw, dict):
        items = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return []

    result = []
    for item in items:
        entry = _normalise_entry(item)
        if not entry:
            continue
        if not include_resolved and entry["status"] == "hersteld":
            continue
        result.append(entry)
    return result


def _describe(inj: dict, lang: str) -> str:
    """Eén blessure als leesbare regel."""
    nl = lang == "nl"
    parts = [inj["area"]]
    meta = []
    if inj["severity"]:
        meta.append((_SEVERITY_LABEL_NL if nl else _SEVERITY_LABEL_EN)[inj["severity"]])
    if inj["status"] and inj["status"] != "actief":
        meta.append(inj["status"] if nl else _STATUS_LABEL_EN.get(inj["status"], inj["status"]))
    if meta:
        parts.append(f"({', '.join(meta)})")
    line = "- " + " ".join(parts)
    if inj["description"]:
        line += f": {inj['description']}"
    extra = []
    if inj["since"]:
        extra.append((f"sinds {inj['since']}" if nl else f"since {inj['since']}"))
    if inj["avoid"]:
        joined = ", ".join(inj["avoid"])
        extra.append((f"vermijden: {joined}" if nl else f"avoid: {joined}"))
    if inj["notes"]:
        extra.append(inj["notes"])
    if extra:
        line += " — " + " | ".join(extra)
    return line


_INSTRUCTIONS_NL = (
    "Deze blessures wegen zwaarder dan elk ander advies. Programmeer of adviseer "
    "geen oefeningen die het aangedane gebied belasten: kies een veilig alternatief "
    "of schaal fors terug, en leg in je coaching-notitie kort uit welke aanpassing "
    "je om welke blessure hebt gedaan. Bewegingen onder \"vermijden\" zijn absoluut "
    "verboden — vervang ze altijd."
)
_INSTRUCTIONS_EN = (
    "These injuries override every other recommendation. Do not program or advise "
    "movements that load the affected area: pick a safe alternative or scale back "
    "sharply, and state briefly in your coaching note which adjustment you made for "
    "which injury. Movements listed under \"avoid\" are strictly forbidden — always "
    "substitute them."
)


def format_injuries_prompt(injuries: list[dict], lang: str = "nl") -> str:
    """Bouw het prompt-blok met actieve blessures. Lege string als er geen zijn."""
    if not injuries:
        return ""
    nl = lang == "nl"
    header = (
        "⚠️ ACTIEVE BLESSURES — verplicht meenemen in het advies:"
        if nl else
        "⚠️ ACTIVE INJURIES — must be taken into account:"
    )
    lines = [_describe(inj, "nl" if nl else "en") for inj in injuries]
    return "\n" + header + "\n" + "\n".join(lines) + "\n" + (_INSTRUCTIONS_NL if nl else _INSTRUCTIONS_EN) + "\n"


def format_injuries_summary(injuries: list[dict], lang: str = "nl") -> str:
    """Korte één-regel samenvatting, bijv. voor een profieltabel."""
    if not injuries:
        return "geen" if lang == "nl" else "none"
    parts = []
    for inj in injuries:
        label = inj["area"]
        bits = [b for b in (inj["severity"], inj["status"] if inj["status"] != "actief" else "") if b]
        if bits:
            label += f" ({', '.join(bits)})"
        parts.append(label)
    return "; ".join(parts)


def injuries_from_gist_files(files: dict, include_resolved: bool = False) -> list[dict]:
    """Gemak: lees blessures direct uit een {bestandsnaam: inhoud} gist-dict."""
    import json  # noqa: PLC0415

    raw = files.get("health_input.json") or ""
    if isinstance(raw, dict):  # sommige callers geven al geparste JSON door
        return parse_injuries(raw, include_resolved)
    try:
        return parse_injuries(json.loads(raw) if raw else {}, include_resolved)
    except (ValueError, TypeError):
        return []
