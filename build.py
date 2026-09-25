"""Build index.html from notes.md (the patch-note text) and sources.json (where each note survives).

    python build.py

Python 3, standard library only. The page is static: one HTML file, no external requests.
Every entry is a <details> element, collapsed by default, with the id `vu-<version>` (`vu-5.7`,
`vu-7.4.x`), so `index.html#vu-5.7` opens and scrolls to VU 5.7."""
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TIER_NAMES = {1: "Official", 2: "MindArk staff", 3: "News bot", 4: "Contemporary copy", 5: "Later compilation"}
TIER_HELP = {
    1: "MindArk's own website, read through the Wayback Machine.",
    2: "Posted by a MindArk employee on a forum.",
    3: "The forum's news bot, which reposted MindArk's notices the day they appeared.",
    4: "Copied at the time by a fan site, download portal or player.",
    5: "Compiled later: wikis, archives, later reposts.",
}
NAMED_ORDER = {"COT Patch 2": (3, 4, 91), "August 2002 patch": (3, 4, 92)}


def version_of(heading):
    version = heading.strip()
    if re.fullmatch(r"\d+", version):
        version += ".0"
    return version


def sort_key(version):
    if version in NAMED_ORDER:
        return NAMED_ORDER[version]
    return tuple(98 if part.upper() == "X" else int(part) for part in version.split("."))


def anchor(version):
    return "vu-" + re.sub(r"\s+", "-", version.lower())


def title(version):
    return version if version in NAMED_ORDER else "VU " + version


def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: '<a href="%s">%s</a>' % (m.group(2).replace('"', "%22"), m.group(1)), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![A-Za-z0-9_])_(?=\S)(.+?)(?<=\S)_(?![A-Za-z0-9_])", r"<em>\1</em>", text)
    return text


def markdown(body):
    """The small Markdown subset notes.md uses: paragraphs (one line per line), bold, italics, links,
    bullet and numbered lists one level deep, `>` quotes and `--` separators."""
    blocks, current = [], None
    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            current = None
            continue
        if line.strip() in ("--", "---"):
            blocks.append(["hr"])
            current = None
            continue
        item = re.match(r"^(\s*)(?:([-*])|(\d+)\.)\s+(.*)$", line)
        if item:
            entry = ("ol" if item.group(3) else "ul", 1 if len(item.group(1)) >= 2 else 0, item.group(4))
            if current and current[0] == "list":
                current[1].append(entry)
            else:
                current = ["list", [entry]]
                blocks.append(current)
            continue
        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            if current and current[0] == "quote":
                current[1].append(quote.group(1))
            else:
                current = ["quote", [quote.group(1)]]
                blocks.append(current)
            continue
        if current and current[0] == "list" and raw.startswith(("  ", "\t")):
            kind, level, text = current[1][-1]
            current[1][-1] = (kind, level, text + "\n" + line.strip())
            continue
        if current and current[0] == "para":
            current[1].append(line.strip())
        else:
            current = ["para", [line.strip()]]
            blocks.append(current)

    out = []
    for block in blocks:
        if block[0] == "hr":
            out.append("<hr>")
        elif block[0] == "para":
            out.append("<p>%s</p>" % "<br>".join(inline(line) for line in block[1]))
        elif block[0] == "quote":
            out.append("<blockquote>%s</blockquote>" % "<br>".join(inline(line) for line in block[1]))
        else:
            items = block[1]
            top = items[0][0]
            out.append("<%s>" % top)
            item_open, nested = False, None
            for kind, level, text in items:
                text = "<br>".join(inline(part) for part in text.split("\n"))
                if level == 0:
                    if nested:
                        out.append("</%s>" % nested)
                        nested = None
                    if item_open:
                        out.append("</li>")
                    out.append("<li>" + text)
                    item_open = True
                else:
                    if not item_open:
                        out.append("<li>")
                        item_open = True
                    if not nested:
                        out.append("<%s>" % kind)
                        nested = kind
                    out.append("<li>%s</li>" % text)
            if nested:
                out.append("</%s>" % nested)
            if item_open:
                out.append("</li>")
            out.append("</%s>" % top)
    return "\n".join(out)


def holds_notes(source):
    """Whether a source carries the notes themselves: a reachable page that is not a preview, a wiki or
    archive compilation, or a player's observations."""
    url = source.get("url", "")
    if not url or source.get("preview") or source.get("names_only"):
        return False
    if re.search(r"entropiamuseum|entropiadirectory|pe-wiki", url):
        return False
    if source["tier"] == 5 and "repost" not in source["label"] and "entropiaplanets.com/wiki" not in url:
        return False
    return True


def source_html(source):
    tier = source["tier"]
    label = html.escape(source["label"])
    link = '<a href="%s">%s</a>' % (html.escape(source["url"]), label) if source.get("url") else label
    archived = re.search(r"web\.archive\.org/web/(\d{4})(\d{2})(\d{2})", source.get("url", ""))
    meta = ' <span class="meta">archived %s-%s-%s</span>' % archived.groups() if archived else ""
    return '<li><span class="tier t%d" title="%s">%s</span> %s%s</li>' % (
        tier, html.escape(TIER_HELP[tier]), TIER_NAMES[tier], link, meta)


def main():
    notes_text = (ROOT / "notes.md").read_text(encoding="utf-8")
    notes = {}
    for heading, body in re.findall(r"^## VU ([^\n]*)\n(.*?)(?=^## VU |\Z)", notes_text, flags=re.M | re.S):
        notes[version_of(heading)] = body.strip("\n")
    data = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["entries"]
    versions = sorted(set(notes) | set(data), key=sort_key)

    unsourced = [v for v in versions if notes.get(v, "").strip()
                 and not any(s.get("url") for s in data.get(v, {}).get("sources", []))]
    if unsourced:
        raise SystemExit("Not built: these entries have notes but no linked source in sources.json: %s"
                         % ", ".join(unsourced))

    parts = []
    for version in versions:
        entry = data.get(version, {})
        body = notes.get(version, "").strip()
        date = entry.get("date", "")
        entry = dict(entry, sources=[s for s in entry.get("sources", []) if s.get("url")])
        findable = any(holds_notes(s) for s in entry["sources"])
        flag = "" if body else ' <span class="flag">%s</span>' % ("sources only" if findable else "no notes found")
        section = ['<details id="%s">' % anchor(version),
                   '<summary><span class="ver">%s</span> <span class="date">%s</span>%s '
                   '<a class="permalink" href="#%s" title="Link to this version">#</a></summary>'
                   % (html.escape(title(version)), html.escape(date), flag, anchor(version)),
                   '<div class="body">']
        note = " ".join(part for part in (entry.get("note"), None if body else entry.get("note_until_transcribed"))
                        if part)
        if note:
            section.append('<p class="note">%s</p>' % html.escape(note))
        if body:
            section.append(markdown(body))
        elif findable:
            section.append('<p class="empty">Not transcribed yet. The sources below hold the notes.</p>')
        elif entry.get("sources"):
            section.append('<p class="empty">No surviving copy of these notes has been found. '
                           'The sources below only name or describe this version.</p>')
        else:
            section.append('<p class="empty">No surviving copy of these notes has been found.</p>')
        origin = entry.get("transcribed_from")
        if body and origin:
            origin = origin if isinstance(origin, list) else [origin]
            section.append('<p class="origin">Transcribed from %s.</p>' % ", ".join(
                '<a href="%s">%s</a>' % (html.escape(o["url"]), html.escape(o["label"])) for o in origin))
        sources = entry.get("sources", [])
        if sources:
            section.append('<h3>Sources</h3>\n<ol class="sources">\n%s\n</ol>' % "\n".join(source_html(s) for s in sources))
        else:
            section.append('<h3>Sources</h3>\n<p class="empty">No source recorded.</p>')
        section.append("</div>\n</details>")
        parts.append("\n".join(section))

    legend = "\n".join('<li><span class="tier t%d">%s</span> %s</li>' % (t, TIER_NAMES[t], html.escape(TIER_HELP[t]))
                       for t in sorted(TIER_NAMES))

    page = TEMPLATE.replace("{{LEGEND}}", legend).replace("{{ENTRIES}}", "\n".join(parts))
    (ROOT / "index.html").write_text(page, encoding="utf-8", newline="\n")
    print("index.html: %d versions, %d with notes" % (len(versions), sum(1 for v in versions if notes.get(v, "").strip())))


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Version Update (VU) Notes · The Project Entropia Preservation Project</title>
<meta name="description" content="Release notes of every Project Entropia and early Entropia Universe version update, VU 3.4 to VU 10, with their sources. Part of the Project Entropia Preservation Project.">
<meta property="og:type" content="website">
<meta property="og:site_name" content="The Project Entropia Preservation Project">
<meta property="og:title" content="Version Update (VU) Notes">
<meta property="og:description" content="Release notes of every Project Entropia and early Entropia Universe version update, VU 3.4 to VU 10, with their sources.">
<style>
:root { --bg: #fdfdfb; --fg: #1d1d1b; --muted: #6b6b66; --line: #deded8; --panel: #f3f3ef; --link: #1a5fb4;
        --t1: #1f7a3a; --t2: #2f5f9e; --t3: #7a5a12; --t4: #6b6b66; --t5: #8a8a84; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161615; --fg: #e6e6e1; --muted: #9c9c95; --line: #33332f; --panel: #1f1f1d; --link: #78aeff;
          --t1: #6fcf8a; --t2: #86b0ea; --t3: #d9b25a; --t4: #a8a8a1; --t5: #86867f; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 24px 16px 64px; }
a { color: var(--link); }
.project { margin: 0 0 4px; color: var(--muted); font-size: .8rem; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; }
h1 { font-size: 1.6rem; margin: 0 0 8px; }
h2 { font-size: 1.1rem; margin: 24px 0 8px; }
h3 { font-size: .95rem; margin: 18px 0 6px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.lede { color: var(--muted); margin: 0 0 16px; }
.controls { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; }
button { font: inherit; font-size: .9rem; padding: 4px 12px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); color: var(--fg); cursor: pointer; }
ul.legend { list-style: none; padding: 0; margin: 0; }
details { border-top: 1px solid var(--line); }
details:last-of-type { border-bottom: 1px solid var(--line); }
summary { cursor: pointer; padding: 10px 4px; list-style-position: outside; }
summary:hover { background: var(--panel); }
.ver { font-weight: 650; }
.date { color: var(--muted); margin-left: 8px; font-variant-numeric: tabular-nums; }
.flag { font-size: .75rem; color: var(--muted); border: 1px solid var(--line); border-radius: 4px; padding: 0 5px; margin-left: 8px; }
.permalink { margin-left: 8px; color: var(--muted); text-decoration: none; visibility: hidden; }
summary:hover .permalink, details[open] .permalink { visibility: visible; }
.body { padding: 0 4px 16px 20px; overflow-wrap: anywhere; }
.note { background: var(--panel); border-left: 3px solid var(--t3); padding: 8px 12px; }
.empty { color: var(--muted); font-style: italic; }
.origin { color: var(--muted); font-size: .85rem; }
blockquote { margin: 8px 0; padding-left: 12px; border-left: 3px solid var(--line); }
hr { border: 0; border-top: 1px dashed var(--line); margin: 16px 0; }
ol.sources { padding-left: 1.4em; }
ol.sources li { margin: 4px 0; }
.tier { display: inline-block; font-size: .72rem; font-weight: 650; text-transform: uppercase; letter-spacing: .03em; border: 1px solid currentColor; border-radius: 4px; padding: 0 5px; margin-right: 4px; white-space: nowrap; }
.t1 { color: var(--t1); } .t2 { color: var(--t2); } .t3 { color: var(--t3); } .t4 { color: var(--t4); } .t5 { color: var(--t5); }
.meta { color: var(--muted); font-size: .85rem; }
ul.legend li { margin: 4px 0; }
</style>
</head>
<body>
<main>
<header>
<p class="project">The Project Entropia Preservation Project</p>
<h1>Version Update (VU) Notes</h1>
<p class="lede">The release notes of Project Entropia, and of Entropia Universe up to VU 10, collected by the Project Entropia Preservation Project.</p>
</header>

<h2>Sources</h2>
<ul class="legend">
{{LEGEND}}
</ul>

<div class="controls">
<button type="button" id="expand">Expand all</button>
<button type="button" id="collapse">Collapse all</button>
</div>

{{ENTRIES}}

</main>
<script>
(function () {
  function target() {
    var id = decodeURIComponent(location.hash.slice(1));
    if (!id) return null;
    var tries = [id, "vu-" + id, id.replace(/^(vu-)?(\\d+)$/, "vu-$2.0"), id.toLowerCase()];
    for (var i = 0; i < tries.length; i++) {
      var el = document.getElementById(tries[i]);
      if (el && el.tagName === "DETAILS") return el;
    }
    return null;
  }
  function openFromHash() {
    var el = target();
    if (el) { el.open = true; el.scrollIntoView(); }
  }
  function setAll(open) {
    var all = document.querySelectorAll("details");
    for (var i = 0; i < all.length; i++) all[i].open = open;
  }
  document.getElementById("expand").addEventListener("click", function () { setAll(true); });
  document.getElementById("collapse").addEventListener("click", function () { setAll(false); });
  window.addEventListener("hashchange", openFromHash);
  openFromHash();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
