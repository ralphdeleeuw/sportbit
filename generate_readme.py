#!/usr/bin/env python3
"""
Generates an up-to-date README.md by sending the repository's source files
to the Claude API and asking it to write clear documentation.
"""

import os
import sys
import anthropic

# ──────────────────────────────────────────────────────────────
# Files to include in the README generation context
# ──────────────────────────────────────────────────────────────

SOURCE_FILES = [
    "autosignup.py",
    "google_calendar_sync.py",
    ".github/workflows/autosignup.yml",
    ".github/workflows/update_readme.yml",
]

def read_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def build_context() -> str:
    parts = []
    for path in SOURCE_FILES:
        content = read_file(path)
        if content:
            parts.append(f"### {path}\n```\n{content}\n```")
        else:
            parts.append(f"### {path}\n_(niet gevonden)_")
    return "\n\n".join(parts)


def generate_readme(context: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""Je bent een technische schrijver. Genereer een duidelijke, professionele README.md in het Engels voor dit project op basis van de onderstaande bronbestanden.

De README moet bevatten:
1. **Project description** — wat doet het project en voor wie
2. **Configuration** — alle secrets die ingesteld moeten worden (SPORTBIT_USERNAME, SPORTBIT_PASSWORD, GOOGLE_CREDENTIALS, CALENDAR_ID, GIST_ID, GIST_TOKEN, PUSHOVER_USER_KEY, PUSHOVER_API_TOKEN, ANTHROPIC_API_KEY) met een korte uitleg per secret
3. **Schedule** — wanneer de workflow runt en hoe dat werkt

Schrijf de README in Markdown. Gebruik geen placeholder tekst. Baseer alles op de werkelijke code.

---

{context}
"""

    message = client.messages.create(
        model="claude-opus-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    print("Reading source files...")
    context = build_context()

    print("Generating README via Claude API...")
    readme = generate_readme(context)

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme)

    print("README.md written successfully.")


if __name__ == "__main__":
    main()
