#!/usr/bin/env python3
"""Generate ``custom_components/cozify_hub/api_spec.json`` from the Cozify Hub API docs.

The integration is *spec driven*: which entities exist for a device, which
attributes are writable, which hub features are known and which endpoints the
documentation lists all come from the generated spec. When the documentation
changes, run this tool (or let the scheduled GitHub workflow do it), review the
diff and release.

Usage::

    python tools/sync_api_docs.py                      # download latest docs
    python tools/sync_api_docs.py --source hub_api.md  # use a local copy
    python tools/sync_api_docs.py --check              # exit 1 if spec is stale
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

DOCS_URL = "https://cozify.github.io/docs/files/hub_api.md"
SPEC_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "cozify_hub"
    / "api_spec.json"
)

VOID = {"br", "hr", "img", "input", "meta", "link"}


class Node:
    def __init__(self, tag: str, parent: Node | None = None) -> None:
        self.tag = tag
        self.parent = parent
        self.children: list[Node | str] = []

    def text(self) -> str:
        out = []
        for child in self.children:
            if isinstance(child, str):
                out.append(child)
            elif child.tag == "br":
                out.append("\n")
            else:
                out.append(child.text())
        return html.unescape("".join(out))

    def find_all(self, tag: str, recursive: bool = True) -> list[Node]:
        found: list[Node] = []
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    found.append(child)
                if recursive:
                    found.extend(child.find_all(tag))
        return found

    def direct(self, tag: str) -> list[Node]:
        return [c for c in self.children if isinstance(c, Node) and c.tag == tag]


class TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.root = Node("root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent  # type: ignore[assignment]
        if node is not self.root:
            self.cur = node.parent  # type: ignore[assignment]

    def handle_data(self, data):
        self.cur.children.append(data)

    def handle_entityref(self, name):
        self.cur.children.append(f"&{name};")

    def handle_charref(self, name):
        self.cur.children.append(f"&#{name};")


def parse_html(fragment: str) -> Node:
    builder = TreeBuilder()
    builder.feed(fragment)
    return builder.root


def section(md: str, start: str, level: str = "###") -> str:
    """Return the markdown between a heading and the next heading of same level."""
    match = re.search(rf"^{re.escape(start)}.*$", md, re.M)
    if not match:
        return ""
    rest = md[match.end() :]
    nxt = re.search(rf"^{re.escape(level)} (?!#)", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def parse_type_cell(cell: Node) -> dict:
    """Interpret a 'Type and allowed values' cell."""
    info: dict = {"type": None, "writable": False}
    nested = cell.find_all("table")
    if nested:
        values = {}
        for row in nested[0].find_all("tr"):
            tds = row.direct("td")
            if len(tds) >= 2:
                values[tds[0].text().strip()] = tds[1].text().strip()
        info["values"] = values
    own = "".join(c if isinstance(c, str) else ("\n" if c.tag == "br" else "")
                  for c in cell.children)
    own = html.unescape(own)
    lowered = cell.text().lower()
    info["writable"] = "writable" in lowered and "read-only" not in lowered.split("writable")[0][-12:]
    if "read-only" in lowered and "writable" not in lowered:
        info["writable"] = False
    own = re.sub(r"read-only|writable", "", own)
    first = own.strip().splitlines()[0].strip() if own.strip() else ""
    m = re.match(r"(\w+)\s*(.*)", first)
    if m:
        info["type"] = m.group(1)
        rest = m.group(2).strip()
        rng = re.search(r"\[([^\]]+)\]", rest)
        if rng:
            info["range"] = rng.group(1)
            rest = rest.replace(rng.group(0), "").strip()
        if rest:
            info["unit"] = rest
    return info


def parse_capabilities(md: str) -> dict[str, dict]:
    body = section(md, "### 6.7 Device capabilities")
    start = body.find("<table>")
    end = body.rfind("</table>")
    if start < 0:
        return {}
    root = parse_html(body[start : end + len("</table>")])
    table = root.find_all("table")[0]
    caps: dict[str, dict] = {}
    current: dict | None = None
    for row in table.find_all("tr", recursive=False) or table.find_all("tbody")[0].direct("tr"):
        tds = row.direct("td")
        if len(tds) < 5:
            continue
        name = tds[0].text().strip()
        if name:
            current = {"description": tds[1].text().strip(), "attributes": []}
            caps[name] = current
        if current is None:
            continue
        attr = tds[2].text().strip()
        if attr and attr != "—":
            entry = {
                "path": attr,
                "description": tds[3].text().strip().replace("—", "").strip(),
                **parse_type_cell(tds[4]),
            }
            current["attributes"].append(entry)
    return caps


def parse_endpoints(md: str) -> list[dict]:
    endpoints = []
    pattern = re.compile(r"^#### (\d+\.\d+\.\d+) `([A-Z]+) (/[^`]*)`", re.M)
    matches = list(pattern.finditer(md))
    for i, m in enumerate(matches):
        chunk = md[m.end() : matches[i + 1].start() if i + 1 < len(matches) else m.end() + 4000]
        access = re.search(r"\*\*Access:\*\*\s*`([A-Z_]+)`", chunk)
        endpoints.append(
            {
                "section": m.group(1),
                "method": m.group(2),
                "path": m.group(3),
                "access": access.group(1) if access else None,
            }
        )
    return endpoints


def parse_features(md: str) -> dict[str, str]:
    body = section(md, "### 6.1 Hub feature codes")
    feats = {}
    pattern = r"<td><code>(\d+)</code>[^<]*(?:<code>[^<]*</code>\)?)?</td>\s*<td><code>([A-Z_0-9]+)</code>"
    for m in re.finditer(pattern, body):
        feats[m.group(1)] = m.group(2)
    return feats


def parse_command_types(md: str) -> list[str]:
    return sorted(set(re.findall(r'"type":\s*"(CMD_[A-Z_]+)"', md)))


def parse_meta(md: str) -> dict:
    rev = re.search(r"Document revision:\s*`([^`]+)`", md)
    date = re.search(r"Document date:\s*`([^`]+)`", md)
    changes = []
    for m in re.finditer(r"^\| `([\d.]+)` \| `([\d-]+)` \| (.+) \|$", md, re.M):
        changes.append({"revision": m.group(1), "date": m.group(2), "summary": m.group(3)})
    return {
        "docs_revision": rev.group(1) if rev else None,
        "docs_date": date.group(1) if date else None,
        "changelog": changes,
    }


def build_spec(md: str, source: str) -> dict:
    return {
        "source": source,
        **parse_meta(md),
        "capabilities": parse_capabilities(md),
        "endpoints": parse_endpoints(md),
        "feature_codes": parse_features(md),
        "command_types": parse_command_types(md),
    }


def load_source(source: str) -> str:
    if re.match(r"https?://", source):
        with urllib.request.urlopen(source, timeout=60) as resp:  # noqa: S310
            return resp.read().decode()
    return Path(source).read_text(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=DOCS_URL)
    ap.add_argument("--out", default=str(SPEC_PATH))
    ap.add_argument("--check", action="store_true", help="fail if spec differs")
    ap.add_argument("--summary", action="store_true", help="print a change summary")
    args = ap.parse_args()

    spec = build_spec(load_source(args.source), args.source)
    out = Path(args.out)
    new = json.dumps(spec, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    old = out.read_text(encoding="utf-8") if out.exists() else ""
    if args.summary and old:
        prev = json.loads(old)
        add_caps = sorted(set(spec["capabilities"]) - set(prev.get("capabilities", {})))
        old_eps = {(e["method"], e["path"]) for e in prev.get("endpoints", [])}
        add_eps = sorted(
            f"{e['method']} {e['path']}"
            for e in spec["endpoints"]
            if (e["method"], e["path"]) not in old_eps
        )
        print(f"docs revision: {prev.get('docs_revision')} -> {spec['docs_revision']}")
        print("new capabilities:", ", ".join(add_caps) or "-")
        print("new endpoints:", ", ".join(add_eps) or "-")
    if args.check:
        if old != new:
            print("api_spec.json is out of date; run tools/sync_api_docs.py", file=sys.stderr)
            return 1
        return 0
    if old != new:
        out.write_text(new, encoding="utf-8")
        print(f"wrote {out} (docs revision {spec['docs_revision']})")
    else:
        print("api_spec.json already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
