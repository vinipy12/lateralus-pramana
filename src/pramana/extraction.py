"""Bounded deterministic HTML extraction; no network, rendering or model calls."""

import json
import re
import unicodedata
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urljoin

from .contracts import digest, normalize_url

VERSION = "htmlparser-v1"
ABOUT = re.compile(r"\b(about|company|who we are|sobre|empresa|über|a propos)\b", re.IGNORECASE)
CONTACT = re.compile(r"\b(contact|contacto|contato|kontakt)\b", re.IGNORECASE)
SOCIAL = re.compile(
    r"https?://(?:www\.)?(?:linkedin\.com|facebook\.com|instagram\.com|x\.com)/", re.IGNORECASE
)
PARKING = re.compile(
    r"domain (?:is )?for sale|buy this domain|domínio à venda|under construction", re.IGNORECASE
)
PHONE = re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d")
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


class Extractor(HTMLParser):
    def __init__(self, url, char_limit, logo_limit):
        super().__init__(convert_charrefs=True)
        self.url = self.base = url
        self.char_limit = char_limit
        self.logo_limit = logo_limit
        self.stack = []
        self.elements = []
        self.links = []
        self.images = []
        self.counts = Counter()
        self.retained = Counter()
        self.truncated = Counter()
        self.used = 0
        self.position = 0
        self.visible = []
        self.json_buffers = []
        self.base_seen = False
        self.overflow_depth = 0

    def add(self, kind, value, location, **extra):
        self.counts[kind] += 1
        if not isinstance(value, str) or not value.strip():
            return
        remaining = self.char_limit - self.used
        text = value.strip()[: max(0, remaining)]
        if len(text) < len(value.strip()):
            self.truncated[kind] += 1
        if not text:
            return
        self.used += len(text)
        self.retained[kind] += 1
        self.elements.append(
            {
                "type": kind,
                "value": text,
                "normalized": normalized(text),
                "location": location,
                **extra,
            }
        )

    def handle_starttag(self, tag, attrs):
        if self.overflow_depth or len(self.stack) >= 128:
            if tag not in VOID:
                self.overflow_depth += 1
            self.counts["depth_limited"] += 1
            return
        attrs = dict(attrs)
        self.position += 1
        location = f"{tag}@{self.position}"
        frame = {"tag": tag, "attrs": attrs, "location": location, "text": []}
        if tag not in VOID:
            self.stack.append(frame)
        if tag == "base" and not self.base_seen and attrs.get("href"):
            self.base = urljoin(self.url, attrs["href"])
            self.base_seen = True
        if tag == "meta":
            if attrs.get("name", "").lower() == "description":
                self.add("description", attrs.get("content", ""), location)
            if attrs.get("http-equiv", "").lower() == "refresh":
                self.add("html_refresh", attrs.get("content", ""), location)
        if tag == "link":
            rel = attrs.get("rel", "").lower().split()
            if "canonical" in rel:
                self.add("canonical", attrs.get("href", ""), location)
            if any("icon" in r for r in rel):
                self.images.append(("icon", attrs.get("href", ""), attrs, location))
        if tag == "img" and any(f["tag"] == "header" for f in self.stack):
            if re.search(
                r"logo",
                " ".join(str(attrs.get(k, "")) for k in ("id", "class", "alt", "src")),
                re.IGNORECASE,
            ):
                self.images.append(("header_logo", attrs.get("src", ""), attrs, location))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.overflow_depth:
            return
        if any(f["tag"] in ("script", "style", "template", "noscript") for f in self.stack):
            if self.stack and self.stack[-1]["tag"] == "script":
                self.stack[-1]["text"].append(data)
            return
        self.visible.append(data)
        # Bound retained buffers by the already bounded input body size.
        for frame in self.stack:
            if frame["tag"] in ("title", "h1", "h2", "h3", "footer", "a", "address"):
                frame["text"].append(data)

    def handle_endtag(self, tag):
        if self.overflow_depth:
            if tag not in VOID:
                self.overflow_depth -= 1
            return
        index = next(
            (i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i]["tag"] == tag), None
        )
        if index is None:
            return
        frames = self.stack[index:]
        del self.stack[index:]
        for frame in reversed(frames):
            self.finish_frame(frame)

    def finish_frame(self, frame):
        tag, attrs, location = frame["tag"], frame["attrs"], frame["location"]
        text = " ".join(frame["text"])
        if tag in ("title", "h1", "h2", "h3", "footer", "address"):
            self.add("heading" if tag.startswith("h") else tag, text, location)
        if tag == "a" and attrs.get("href"):
            self.links.append({"href": attrs["href"], "text": text, "location": location})
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self.json_buffers.append(("".join(frame["text"]), location))

    def structured(self, obj, path, depth=0):
        if depth > 30:
            return
        if isinstance(obj, list):
            for i, child in enumerate(obj):
                self.structured(child, f"{path}[{i}]", depth + 1)
        elif isinstance(obj, dict):
            kind = obj.get("@type", [])
            kinds = [kind] if isinstance(kind, str) else kind
            if isinstance(kinds, list) and any(
                k in ("Organization", "Corporation", "LocalBusiness") for k in kinds
            ):
                for key in ("name", "legalName", "url", "telephone", "address", "sameAs"):
                    if key in obj:
                        self.add(
                            "organization_" + key,
                            json.dumps(obj[key], ensure_ascii=False)
                            if not isinstance(obj[key], str)
                            else obj[key],
                            path + "." + key,
                        )
                logo = obj.get("logo")
                if isinstance(logo, str):
                    self.images.append(("organization_logo", logo, {}, path + ".logo"))
                elif isinstance(logo, dict):
                    self.images.append(
                        (
                            "organization_logo",
                            logo.get("url", logo.get("contentUrl", "")),
                            logo,
                            path + ".logo",
                        )
                    )
            for key, child in obj.items():
                if isinstance(child, (dict, list)):
                    self.structured(child, path + "." + key, depth + 1)

    def finish(self):
        for frame in reversed(self.stack):
            self.finish_frame(frame)
        self.stack.clear()
        for value, location in self.json_buffers:
            try:
                self.structured(json.loads(value), location)
            except (ValueError, RecursionError):
                self.counts["invalid_structured_data"] += 1
        links = []
        for link in self.links:
            try:
                url = normalize_url(urljoin(self.base, link["href"]))
            except ValueError:
                continue
            category = (
                "about"
                if ABOUT.search(link["text"] + " " + url)
                else ("contact" if CONTACT.search(link["text"] + " " + url) else None)
            )
            if category:
                links.append({"url": url, "category": category})
                self.add(category + "_link", url, link["location"])
            if SOCIAL.match(url):
                self.add("social_url", url, link["location"])
        logos, seen = [], set()
        for source, original, attrs, location in self.images:
            self.counts["logo"] += 1
            try:
                url = normalize_url(urljoin(self.base, original))
            except (ValueError, TypeError):
                continue
            if url in seen:
                continue
            seen.add(url)
            if len(logos) >= self.logo_limit:
                self.truncated["logo"] += 1
                continue
            logo = {
                "source_type": source,
                "original_url": original,
                "resolved_url": url,
                "alt": attrs.get("alt"),
                "width": attrs.get("width"),
                "height": attrs.get("height"),
                "media_type": attrs.get("type"),
                "location": location,
                "verified": False,
            }
            logo["candidate_id"] = digest(logo)
            logos.append(logo)
            self.retained["logo"] += 1
        visible = " ".join(" ".join(self.visible).split())
        for match in PHONE.finditer(visible):
            self.add("phone", match.group(), "visible-text", offsets=[match.start(), match.end()])
        for match in PARKING.finditer(visible):
            self.add(
                "parking_indicator",
                match.group(),
                "visible-text",
                offsets=[match.start(), match.end()],
            )
        self.add("body", visible, "visible-text", offsets=[0, len(visible)])
        for i, element in enumerate(self.elements):
            element["element_id"] = digest({"index": i, **element})
        counts = {
            kind: {
                "examined": count,
                "retained": self.retained[kind],
                "dropped": count - self.retained[kind],
                "truncated": self.truncated[kind],
            }
            for kind, count in sorted(self.counts.items())
        }
        return (
            self.elements,
            logos,
            sorted(links, key=lambda link: (link["category"], link["url"])),
            counts,
        )


def extract(body, url, policy, content_type="text/html"):
    page = {
        "parser_version": VERSION,
        "normalization_version": "nfkc-casefold-v1",
        "pattern_version": "multilingual-small-v1",
        "final_url": url,
        "input_bytes": len(body),
        "elements": [],
        "logos": [],
        "links": [],
        "counts": {},
        "unsupported_media": "html" not in content_type,
        "retained_characters": 0,
    }
    if not page["unsupported_media"]:
        parser = Extractor(url, policy["page_chars"], policy["page_logos"])
        charset = re.search(r"charset=([\w-]+)", content_type)
        encoding = charset.group(1) if charset else "utf-8"
        try:
            text = body.decode(encoding, errors="replace")
        except LookupError:
            text = body.decode("utf-8", errors="replace")
        parser.feed(text)
        parser.close()
        page["elements"], page["logos"], page["links"], page["counts"] = parser.finish()
        page["retained_characters"] = parser.used
    page["truncated"] = any(c["truncated"] for c in page["counts"].values())
    page["page_id"] = digest(page)
    for element in page["elements"]:
        element["page_id"] = page["page_id"]
    for logo in page["logos"]:
        logo["page_id"] = page["page_id"]
    return page
