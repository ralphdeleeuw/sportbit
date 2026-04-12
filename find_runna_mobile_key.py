"""
find_runna_mobile_key.py — Extraheer de Runna mobile API-key uit de Android APK.

Gebruik:
    python3 find_runna_mobile_key.py runna.apk

De APK is een ZIP-bestand. Dit script scant alle bestanden daarin op:
  - AppSync API-keys (patroon: da2-[a-z0-9]{26})
  - GraphQL-endpoint URLs
  - Platform-source header-waarden

Stappen:
  1. Download de Runna APK:
       https://apkpure.com/runna-running-training-plans/com.runna.app/download
       of: https://www.apkmirror.com/  (zoek "Runna")
  2. Sla op als runna.apk
  3. Voer dit script uit: python3 find_runna_mobile_key.py runna.apk
  4. Kopieer de gevonden mobile API-key
  5. Voeg toe als GitHub Secret: RUNNA_MOBILE_API_KEY

Na instellen van het secret wordt de mobile API-key automatisch gebruikt
door fetch_runna.py bij de volgende workflow-run.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path


# AppSync API-key patroon: da2- gevolgd door 26 alphanumerieke tekens
API_KEY_RE   = re.compile(rb"da2-[a-zA-Z0-9]{26}")

# GraphQL-endpoint patroon
GRAPHQL_RE   = re.compile(rb"https://[a-zA-Z0-9._-]+\.appsync-api\.[a-zA-Z0-9-]+\.amazonaws\.com/graphql"
                          rb"|https://[a-zA-Z0-9._-]*runna[a-zA-Z0-9._-]*/graphql")

# Platform-source waarden
PLATFORM_RE  = re.compile(rb"rb-(?:ios|android|mobile|app)\b")


def scan_apk(apk_path: str) -> None:
    path = Path(apk_path)
    if not path.exists():
        print(f"Bestand niet gevonden: {apk_path}")
        sys.exit(1)

    api_keys: set[str]  = set()
    endpoints: set[str] = set()
    platforms: set[str] = set()

    print(f"Scannen: {apk_path} ({path.stat().st_size // 1024 // 1024} MB)\n")

    with zipfile.ZipFile(apk_path) as z:
        names = z.namelist()
        print(f"Bestanden in APK: {len(names)}")

        for name in names:
            # Scan DEX, assets, native libs en XML-bestanden
            ext = name.lower().rsplit(".", 1)[-1]
            if ext not in ("dex", "xml", "json", "properties", "txt",
                           "so", "js", "html", "config"):
                if "assets/" not in name and "res/" not in name:
                    continue
            try:
                data = z.read(name)
            except Exception:
                continue

            for m in API_KEY_RE.finditer(data):
                key = m.group(0).decode()
                if key not in api_keys:
                    api_keys.add(key)
                    print(f"  [API-key] {key}  (in {name})")

            for m in GRAPHQL_RE.finditer(data):
                ep = m.group(0).decode()
                if ep not in endpoints:
                    endpoints.add(ep)
                    print(f"  [GraphQL] {ep}  (in {name})")

            for m in PLATFORM_RE.finditer(data):
                val = m.group(0).decode()
                if val not in platforms:
                    platforms.add(val)
                    print(f"  [platform-source] {val}  (in {name})")

    print("\n" + "=" * 60)
    print("SAMENVATTING")
    print("=" * 60)

    web_key = "da2-p6hunb5zafhn7ngpf6jtotnjvm"  # bekende web-key
    mobile_keys = api_keys - {web_key}

    if mobile_keys:
        print(f"\nMobile API-keys gevonden ({len(mobile_keys)}):")
        for k in sorted(mobile_keys):
            print(f"  {k}")
        print("\nVolgende stap:")
        print("  Ga naar GitHub → Settings → Secrets and variables → Actions")
        print("  Voeg toe: RUNNA_MOBILE_API_KEY = <key hierboven>")
    elif api_keys:
        print(f"\nAlleen bekende web API-key gevonden: {web_key}")
        print("Mogelijke verklaringen:")
        print("  - Runna gebruikt dezelfde key voor web en mobile")
        print("  - De key staat in een native library (.so) — probeer: strings runna.apk | grep da2-")
    else:
        print("\nGeen AppSync API-keys gevonden in DEX/assets.")
        print("Probeer: strings runna.apk | grep -E 'da2-[a-z0-9]{26}'")

    if endpoints:
        mobile_endpoints = {e for e in endpoints if "hydra" not in e or "runna" not in e}
        if mobile_endpoints:
            print(f"\nAndere GraphQL-endpoints:")
            for e in sorted(mobile_endpoints):
                print(f"  {e}")

    if platforms:
        non_web = platforms - {"rb-web"}
        if non_web:
            print(f"\nMobile platform-source waarden: {sorted(non_web)}")
            print("Gebruik een van deze als x-rb-platform-source in de scraper.")


if __name__ == "__main__":
    apk = sys.argv[1] if len(sys.argv) > 1 else "runna.apk"
    scan_apk(apk)
