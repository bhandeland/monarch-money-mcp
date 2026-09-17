#!/usr/bin/env python3
"""Download Monarch's GraphQL schema into .schema/monarch_schema.json.

Monarch disables introspection for regular users, but its web app ships a copy
of the schema (an introspection result) inside its main JS bundle. This finds
the current bundle from app.monarch.com and extracts that copy. The tests use
it to validate every GraphQL operation this server sends.
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

APP_URL = "https://app.monarch.com/"
OUT = Path(__file__).resolve().parent.parent / ".schema" / "monarch_schema.json"
MARKER = "JSON.parse('{\"__schema\""

JS_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "monarch-money-mcp schema fetch"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body: bytes = response.read()
        return body.decode("utf-8")


def js_unescape(literal: str) -> str:
    """Decode the body of a single-quoted JavaScript string literal."""
    def replace(m: re.Match[str]) -> str:
        esc = m.group(1)
        if esc.startswith("x"):
            return chr(int(esc[1:], 16))
        if esc.startswith("u{"):
            return chr(int(esc[2:-1], 16))
        if esc.startswith("u"):
            return chr(int(esc[1:], 16))
        if esc == "\n":
            return ""
        return JS_ESCAPES.get(esc, esc)
    return re.sub(r"\\(x[0-9a-fA-F]{2}|u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|.|\n)", replace, literal)


def extract_schema(bundle: str) -> dict[str, object]:
    start = bundle.index(MARKER) + len("JSON.parse('")
    end = start
    while bundle[end] != "'":
        end += 2 if bundle[end] == "\\" else 1
    # JSON escapes like \" arrive doubled (\\"), so decode the JS layer first,
    # then parse the JSON. Surrogate pairs from \uD83D\uDE00-style escapes are rejoined.
    text = js_unescape(bundle[start:end]).encode("utf-16", "surrogatepass").decode("utf-16")
    schema: dict[str, object] = json.loads(text)["__schema"]
    return schema


def main() -> None:
    index = fetch(APP_URL)
    scripts = re.findall(r'src="(https://static\.monarch\.com/static/js/main\.[0-9a-f]+\.js)"', index)
    if not scripts:
        sys.exit(f"Couldn't find the main bundle in {APP_URL}")
    schema = extract_schema(fetch(scripts[0]))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(schema))
    types = schema["types"]
    assert isinstance(types, list)
    print(f"Saved {len(types)} types from {scripts[0].rsplit('/', 1)[-1]} to {OUT}")


if __name__ == "__main__":
    main()
