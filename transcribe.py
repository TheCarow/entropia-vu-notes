"""Fill the "sources only" entries of notes.md from the sources listed for them in sources.json.

    python transcribe.py --dry-run            # report what would be transcribed, text not shown
    python transcribe.py                      # write the transcriptions into notes.md, then rebuild
    python transcribe.py --only 5.2,7.6.2     # just these versions
    python transcribe.py --refresh            # ignore the page cache and fetch again

For each version with no text in notes.md, the sources are tried best first. Previews, wiki
compilations and player observations are skipped, because they are not the notes. The first source
that yields text is used, and the entry in sources.json records it under "transcribed_from", so the
page says where the text came from. A section that already has text is never touched unless
--overwrite is given.

Pages are fetched once and kept in .cache/ (git-ignored). Wayback Machine requests are spaced 3.5 s
apart and forum requests 1 s apart. Python 3, standard library only."""
import argparse
import datetime
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import build

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache"
USER_AGENT = "Mozilla/5.0 (Project Entropia patch-notes preservation; read-only)"
MIN_CHARS = 60
_last_request = {}


# ---------------------------------------------------------------------------------------------
# Fetching

def fetch(url, refresh=False):
    """Return the body of url as text, from the cache when present. None when it cannot be had."""
    url = url.split("#", 1)[0]
    CACHE.mkdir(exist_ok=True)
    path = CACHE / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".txt")
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    host = "wayback" if "web.archive.org" in url else "other"
    gap = 3.5 if host == "wayback" else 1.0
    for wait in (0, 10, 30, 60):
        pause = gap - (time.time() - _last_request.get(host, 0))
        time.sleep(max(0, pause) + wait)
        _last_request[host] = time.time()
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504):
                continue
            return None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        path.write_text(text, encoding="utf-8")
        return text
    return None


def original(url):
    """The Wayback replay of url without the Wayback toolbar (the id_ form)."""
    return re.sub(r"(web\.archive\.org/web/\d{14})/", r"\1id_/", url)


# ---------------------------------------------------------------------------------------------
# HTML and BBCode to the Markdown subset build.py renders

class Markdown(HTMLParser):
    BLOCK = {"p", "div", "table", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "center",
             "form", "dd", "dt", "dl", "pre"}
    SKIP = {"script", "style", "noscript", "form", "select", "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.line, self.skip, self.lists, self.bold, self.italic, self.href = [], "", 0, [], 0, 0, None
        self.link_text = ""

    def newline(self):
        text = re.sub(r"[ \t ]+", " ", self.line).strip()
        text = re.sub(r"\*\*\s*\*\*", "", text)
        if text and text not in ("-", "**", "_"):
            self.lines.append(text)
        self.line = ""

    def blank(self):
        self.newline()
        if self.lines and self.lines[-1] != "":
            self.lines.append("")

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "br":
            self.newline()
        elif tag in ("ul", "ol"):
            self.newline()
            self.lists.append([tag, 0])
        elif tag == "li":
            self.newline()
            depth = max(len(self.lists), 1)
            kind = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            marker = "%d." % kind[1] if kind[0] == "ol" else "-"
            self.line = "    " * (depth - 1) + marker + " "
        elif tag in ("b", "strong") or re.fullmatch(r"h[1-6]", tag):
            if re.fullmatch(r"h[1-6]", tag):
                self.blank()
            self.bold += 1
            if self.bold == 1:
                self.line += "**"
        elif tag in ("i", "em"):
            self.italic += 1
            if self.italic == 1:
                self.line += "_"
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if re.match(r"https?://", href) and "web.archive.org" not in href:
                self.href, self.link_text = href, ""
        elif tag == "hr":
            self.blank()
            self.lines.extend(["--", ""])
        elif tag in self.BLOCK:
            self.blank() if tag in ("p", "table", "blockquote", "center") else self.newline()

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("ul", "ol"):
            self.newline()
            if self.lists:
                self.lists.pop()
            if not self.lists:
                self.blank()
        elif tag == "li":
            self.newline()
        elif tag in ("b", "strong") or re.fullmatch(r"h[1-6]", tag):
            if self.bold == 1:
                self.line = self.line.rstrip() + "**"
            self.bold = max(0, self.bold - 1)
            if re.fullmatch(r"h[1-6]", tag):
                self.newline()
        elif tag in ("i", "em"):
            if self.italic == 1:
                self.line = self.line.rstrip() + "_"
            self.italic = max(0, self.italic - 1)
        elif tag == "a" and self.href:
            text = self.link_text.strip()
            if text:
                self.line = self.line[: len(self.line) - len(self.link_text)] + "[%s](%s)" % (text, self.href)
            self.href = None
        elif tag in self.BLOCK:
            self.blank() if tag in ("p", "table", "blockquote", "center") else self.newline()

    def handle_data(self, data):
        if self.skip:
            return
        data = data.replace("\r", "").replace("\n", " ")
        self.line += data
        if self.href:
            self.link_text += data

    def result(self):
        self.newline()
        text = "\n".join(self.lines)
        return tidy(text)


def tidy(text):
    text = re.sub(r"\*\*(\s*)\*\*", r"\1", text)
    text = re.sub(r"__", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_md(fragment):
    parser = Markdown()
    parser.feed(fragment)
    parser.close()
    return parser.result()


def bbcode_to_md(raw):
    """Forum posts: vBulletin BBCode as imported into Discourse, sometimes already Markdown."""
    text = raw.replace("\r", "")
    text = re.sub(r"\[/?(?:size|color|font|center|left|right|indent|u|highlight|wrap|align)(?:=[^\]]*)?\]", "", text,
                  flags=re.I)
    text = re.sub(r"\[img\].*?\[/img\]", "", text, flags=re.I | re.S)
    text = re.sub(r"\[url=([^\]]+)\](.*?)\[/url\]", r"[\2](\1)", text, flags=re.I | re.S)
    text = re.sub(r"\[url\](.*?)\[/url\]", r"\1", text, flags=re.I | re.S)
    text = re.sub(r"\[/?b\]", "**", text, flags=re.I)
    text = re.sub(r"\[/?i\]", "_", text, flags=re.I)
    text = re.sub(r"\[(?:list|ul|ol)(?:=[^\]]*)?\]", "\n", text, flags=re.I)
    text = re.sub(r"\[/(?:list|ul|ol)\]", "\n", text, flags=re.I)
    text = re.sub(r"\[(?:\*|li)\]\s*", "\n- ", text, flags=re.I)
    text = re.sub(r"\[/li\]", "", text, flags=re.I)
    text = re.sub(r"\[hr\]", "\n--\n", text, flags=re.I)
    text = re.sub(r"\[quote[^\]]*\].*?\[/quote\]", "", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    if re.search(r"<(?:p|ul|li|b|strong|div)\b", text, re.I):
        text = html_to_md(text)
    text = text.replace("\\_", "_").replace("\\*", "*").replace("\\[", "[").replace("\\]", "]")
    text = html.unescape(text)
    lines = [line.strip() if not re.match(r"\s+[-*] ", line) else line.rstrip() for line in text.split("\n")]
    return tidy("\n".join(lines))


# ---------------------------------------------------------------------------------------------
# Picking the right item out of a page that lists several

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"], 1)}


def parse_date(text):
    text = text.lower()
    match = re.search(r"\b(\d{1,2})\s+([a-z]{3})[a-z]*\.?\s+(\d{4})\b", text)
    if match and match.group(2) in MONTHS:
        return datetime.date(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if match:
        return datetime.date(*map(int, match.groups()))
    match = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text)
    if match:
        return datetime.date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    return None


def norm(text):
    return re.sub(r"[^a-z0-9]", "", html.unescape(text).lower())


def pick(items, source, version):
    """items: list of (title, date_text, body_html). Choose the one the source describes."""
    wanted_title = norm(source["label"].split(" — ", 1)[-1])
    wanted_date = parse_date(source.get("date", "")) if source.get("date") else None
    numbered = re.fullmatch(r"\d+(?:\.\d+)+", version)
    best, best_score = None, 0
    for title, date_text, body in items:
        score = 0
        t = norm(title + " " + date_text)
        if t and (t == wanted_title or wanted_title.startswith(norm(title)) and len(norm(title)) >= 6):
            score += 3
        elif norm(title) and norm(title) in wanted_title:
            score += 2
        if numbered and re.search(r"(?<![\d.])%s(?![\d])" % re.escape(version), title):
            score += 2
        item_date = parse_date(date_text)
        if wanted_date and item_date:
            gap = abs((item_date - wanted_date).days)
            score += 3 if gap == 0 else (1 if gap <= 3 else -2)
        if score > best_score:
            best, best_score = body, score
    return best if best_score >= 3 else None


# ---------------------------------------------------------------------------------------------
# One extractor per page layout. Each returns Markdown text or None.

def between(text, start, end):
    i = text.find(start)
    if i < 0:
        return None
    j = text.find(end, i + len(start))
    return text[i + len(start): j if j >= 0 else len(text)]


def element(text, pattern):
    """The inner HTML of the first element whose opening tag matches pattern, nesting counted."""
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    tag = re.match(r"<(\w+)", match.group(0)).group(1).lower()
    depth, i = 1, match.end()
    for m in re.finditer(r"<(/?)%s\b[^>]*>" % tag, text[i:], re.I):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return text[i: i + m.start()]
    return text[i:]


def x_forum(url, source, version, refresh):
    match = re.match(r"https://forum\.entropiauniverse\.com/t/(?:[^/\d][^/]*/)?(\d+)(?:/(\d+))?/?$", url)
    if not match:
        return None
    body = fetch("https://forum.entropiauniverse.com/posts/by_number/%s/%s.json" % (match.group(1), match.group(2) or 1),
                 refresh)
    if not body:
        return None
    raw = json.loads(body).get("raw") or ""
    return bbcode_to_md(raw)


def x_pe_content(url, source, version, refresh):
    """project-entropia.com .ajp pages, 2003-2006: each item between CONTENT n START/END comments."""
    page = fetch(original(url), refresh)
    if not page:
        return None
    blocks = []
    for start in re.finditer(r"<!--CONTENT (\d+) START-->", page):
        end = page.find("<!--CONTENT %s END-->" % start.group(1), start.end())
        blocks.append((start.group(1), page[start.end(): end if end >= 0 else len(page)]))
    innermost = [(n, b) for n, b in blocks if "<!--CONTENT " not in b]
    items = []
    blocks = innermost + [(n, b) for n, b in blocks if (n, b) not in innermost]
    for _, block in innermost:
        head = re.search(r"<b>(.*?)</b>(?:&nbsp;|\s)*(?:<font[^>]*>)?\s*([^<]*)", block, re.I | re.S)
        if not head:
            continue
        title = re.sub(r"<[^>]+>", "", head.group(1)).strip()
        date_text = head.group(2).strip()
        body = block[head.end():]
        items.append((title, date_text, body))
    if not items:
        # Some news pages carry no CONTENT comments: each item is a table whose grey first row holds the
        # bold title and the date, and whose second row holds the text.
        for match in re.finditer(r"<tr bgcolor=#f0f0f0><td[^>]*>\s*<b>(.*?)</b>(?:&nbsp;|\s)*(?:<font[^>]*>)?\s*([^<]*)"
                                 r"</td></tr>\s*<tr><td[^>]*>(.*?)</td></tr>\s*</table>", page, re.I | re.S):
            items.append((re.sub(r"<[^>]+>", "", match.group(1)).strip(), match.group(2).strip(), match.group(3)))
    if "StdContent.ajp" in url or "Content.ajp" in url:
        wanted = re.search(r"Id=(\d+)", url, re.I)
        chosen = [b for n, b in blocks if wanted and n == wanted.group(1)]
        if chosen:
            text = chosen[0]
            text = re.sub(r"^.*?<b>.*?</b>", "", text, count=1, flags=re.S | re.I)
            return html_to_md(text)
    body = pick(items, source, version)
    return html_to_md(body) if body else None


def x_eu_newslist(url, source, version, refresh):
    """entropiauniverse.com support news and news archive, 2006-2008: title span, then a date span and the body."""
    page = fetch(original(url), refresh)
    if not page:
        return None
    # 2007-2008 pages title an item with a bold span, 2006 pages with a white-on-grey table cell.
    heads = list(re.finditer(r'<(span|td)[^>]*class="text_(?:black_11_bold|white_11)"[^>]*>(.*?)</\1>', page, re.S))
    items = []
    for index, head in enumerate(heads):
        title = re.sub(r"<[^>]+>", "", head.group(2)).strip()
        stop = heads[index + 1].start() if index + 1 < len(heads) else len(page)
        rest = page[head.end(): stop]
        cell = element(rest, r'<td[^>]*class="text_black_11"[^>]*>') or ""
        date = re.search(r'<span class="text_grey">(.*?)</span>', cell, re.S)
        date_text = re.sub(r"<[^>]+>", "", date.group(1)).strip() if date else ""
        body = cell[date.end():] if date else cell
        items.append((title, date_text, body))
    body = pick(items, source, version)
    if body is None and len(items) == 1:
        body = items[0][2]
    return html_to_md(body) if body else None


def x_eu_rich(url, source, version, refresh):
    """entropiauniverse.com single-document pages (content lists, previews)."""
    page = fetch(original(url), refresh)
    if not page:
        return None
    cells = re.findall(r'<td[^>]*class="text_black_11"[^>]*>(.*?)</td>', page, re.S | re.I)
    body = max(cells, key=len) if cells else None
    return html_to_md(body) if body else None


def x_eu_xml(url, source, version, refresh):
    """entropiauniverse.com / planetcalypso.com support-faq and news pages, 2009-2010."""
    page = fetch(original(url), refresh)
    if not page:
        return None
    body = element(page, r'<div[^>]*class="text-component"[^>]*>')
    return html_to_md(body) if body else None


def x_pioneers(url, source, version, refresh):
    """Entropia Pioneers forum (phpBB 2): the first post of the topic."""
    page = fetch(original(url), refresh)
    if not page:
        return None
    body = element(page, r'<span class="postbody"[^>]*>')
    return html_to_md(body) if body else None


def x_pe_forum2002(url, source, version, refresh):
    """The 2002 official forum: the first post, after its date line."""
    page = fetch(original(url), refresh)
    if not page:
        return None
    body = element(page, r'<td class="breadtext" colspan="4"[^>]*>')
    if not body:
        return None
    body = re.sub(r"^\s*[A-Z][a-z]+ \d{1,2}, \d{4}[^<]*(?:<br\s*/?>\s*)*", "", body, flags=re.I)
    return html_to_md(body)


def x_perc(url, source, version, refresh):
    """perc.info, 2004: the listing inside td#documentElement."""
    page = fetch(original(url), refresh)
    if not page:
        return None
    body = element(page, r"<td id=\"?documentElement\"?[^>]*>")
    if not body:
        return None
    text = html_to_md(body)
    return re.sub(r"^vu\s?\d[\d.]*\s*\n", "", text, flags=re.I)


def x_wiki(url, source, version, refresh):
    """EntropiaPlanets wiki (MediaWiki): the text after the infobox, up to the first section heading."""
    page = fetch(original(url), refresh)
    if not page:
        return None
    content = element(page, r'<div[^>]*id="mw-content-text"[^>]*>') or ""
    content = content.split("<h2", 1)[0]
    content = re.sub(r"<table.*?</table>", "", content, flags=re.S | re.I)
    content = re.sub(r'<div style="text-align:right;">.*?</div>', "", content, flags=re.S | re.I)
    return html_to_md(content)


EXTRACTORS = [
    (r"forum\.entropiauniverse\.com/t/", x_forum),
    (r"project-entropia\.com(?::80)?/forum/viewthread", x_pe_forum2002),
    (r"project-entropia\.com(?::80)?/(?:news/Index|StdContent|Content)\.ajp", x_pe_content),
    (r"entropiauniverse\.com(?::80)?/(?:pe/)?en/rich/(?:5377|5078|5080|6717)\.html", x_eu_newslist),
    (r"entropiauniverse\.com(?::80)?/(?:pe/)?en/rich/\d+\.html", x_eu_rich),
    (r"(?:entropiauniverse|planetcalypso)\.com(?::80)?/(?:support-faq|news)/pages/", x_eu_xml),
    (r"entropia-pioneers\.kicks-ass\.org", x_pioneers),
    (r"perc\.info", x_perc),
    (r"entropiaplanets\.com(?::80)?/wiki/", x_wiki),
]


def usable(source):
    """A source whose text is the notes (build.holds_notes) and whose page layout this tool can read."""
    return build.holds_notes(source) and any(re.search(pattern, source["url"]) for pattern, _ in EXTRACTORS)


def describes_changes(source):
    """A source whose label promises the list of changes, not a downtime notice about them."""
    label = source["label"].lower()
    return "notice" not in label and bool(re.search(r"content|listing|release notes|fixed issues|update|patch|notes",
                                                    label))


def downtime_only(text):
    """A short server-downtime announcement rather than a list of changes."""
    return len(text) < 500 and bool(re.search(r"temporarily unavailable|servers? (?:will be|are|have been) (?:taken )?down",
                                              text, re.I))


def extract(source, version, refresh):
    for pattern, extractor in EXTRACTORS:
        if re.search(pattern, source["url"]):
            try:
                return extractor(source["url"], source, version, refresh)
            except Exception as error:  # a malformed page should not stop the run
                print("  ! %s: %s" % (version, error), file=sys.stderr)
                return None
    return None


# ---------------------------------------------------------------------------------------------

def collect_mini_updates(candidates, version, refresh):
    """An `.X` entry gathers the unnumbered mini-updates between two versions: every dated item, once each,
    from its best source, oldest first, each under its date. Returns (first source used, text) or None."""
    taken = {}
    for source in candidates:
        date = parse_date(source.get("date", "")) if source.get("date") else None
        if date is None or any(abs((date - d).days) <= 1 for d in taken):
            continue
        text = extract(source, version, refresh)
        if text and len(text) >= MIN_CHARS and not downtime_only(text):
            taken[date] = (source, text)
    if not taken:
        return None
    ordered = [taken[d] for d in sorted(taken)]
    if len(ordered) == 1:
        return [ordered[0][0]], ordered[0][1]
    text = "\n\n".join("**%s**\n%s" % (d.strftime("%d %b %Y").lstrip("0"), taken[d][1]) for d in sorted(taken))
    return [source for source, _ in ordered], text


def sections(text):
    """notes.md as an ordered list of [heading, body]."""
    parts = re.split(r"^(## VU [^\n]*)\n", text, flags=re.M)
    return parts[0], [[parts[i], parts[i + 1]] for i in range(1, len(parts), 2)]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="report only; write nothing and show no text")
    parser.add_argument("--only", help="comma-separated versions")
    parser.add_argument("--overwrite", action="store_true", help="also replace sections that already have text")
    parser.add_argument("--refresh", action="store_true", help="fetch pages again instead of using .cache/")
    args = parser.parse_args()

    notes_path, sources_path = ROOT / "notes.md", ROOT / "sources.json"
    preamble, secs = sections(notes_path.read_text(encoding="utf-8"))
    body_of = {build.version_of(h[len("## VU "):]): b for h, b in secs}
    data = json.loads(sources_path.read_text(encoding="utf-8"))
    entries = data["entries"]
    wanted = set(v.strip() for v in args.only.split(",")) if args.only else None

    targets = [v for v in sorted(entries, key=build.sort_key)
               if (wanted is None or v in wanted) and (args.overwrite or not body_of.get(v, "").strip())]
    done, report = {}, []
    for version in targets:
        candidates = sorted((s for s in entries[version]["sources"] if usable(s)),
                            key=lambda s: (s["tier"], 0 if describes_changes(s) else 1))
        result, fallback = None, None
        if version.endswith(".X"):
            result = collect_mini_updates(candidates, version, args.refresh)
        else:
            for source in candidates:
                text = extract(source, version, args.refresh)
                if not text or len(text) < MIN_CHARS:
                    continue
                if downtime_only(text):
                    fallback = fallback or ([source], text)
                    continue
                result = ([source], text)
                break
        result = result or fallback
        if not result:
            report.append((version, "-", 0, 0, 0, "no usable source" if not candidates else "extraction failed"))
            continue
        used, text = result
        lines = [line for line in text.split("\n") if line.strip()]
        bullets = sum(1 for line in lines if re.match(r"\s*(?:[-*]|\d+\.) ", line))
        status = "tier %s" % ",".join(str(s["tier"]) for s in used)
        if len(used) > 1:
            status += ", %d items" % len(used)
        report.append((version, used[0]["label"].split(" — ")[0], len(text), len(lines), bullets, status))
        done[version] = (used, text)

    print("%-18s %-26s %7s %6s %7s  %s" % ("version", "source", "chars", "lines", "bullets", "status"))
    for row in report:
        print("%-18s %-26s %7d %6d %7d  %s" % (row[0], row[1][:26], row[2], row[3], row[4], row[5]))
    print("\n%d of %d entries transcribable." % (len(done), len(targets)))
    if args.dry_run or not done:
        return

    heading_of = {build.version_of(h[len("## VU "):]): i for i, (h, _) in enumerate(secs)}
    for version, (used, text) in done.items():
        if version in heading_of:
            secs[heading_of[version]][1] = text + "\n"
        else:
            secs.append(["## VU %s" % version, text + "\n"])
        entries[version]["transcribed_from"] = [{"label": s["label"], "url": s["url"]} for s in used]
    secs.sort(key=lambda s: build.sort_key(build.version_of(s[0][len("## VU "):])))
    notes_path.write_text(preamble + "".join("%s\n%s" % (h, b if b.endswith("\n") else b + "\n") for h, b in secs),
                          encoding="utf-8", newline="\n")
    sources_path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    print("notes.md and sources.json updated.")
    build.main()


if __name__ == "__main__":
    main()
