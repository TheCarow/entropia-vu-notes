# Version Update (VU) Notes

Part of **The Project Entropia Preservation Project**. A single static page preserving the release
notes of every Project Entropia version update, and of Entropia Universe up to VU 10. Each version is
a collapsed entry that lists where its notes survive, primary sources first.

## Files

| File | What it is |
|---|---|
| `index.html` | The page. Generated, so don't edit it by hand. GitHub Pages serves it. |
| `notes.md` | The notes' text, one `## VU <version>` section per version. |
| `sources.json` | Each version's date, an optional editorial note, and its ranked sources. |
| `build.py` | Rebuilds `index.html` from the two files above. Python 3, standard library only. |
| `transcribe.py` | Fills the "sources only" entries of `notes.md` from their listed sources, then rebuilds. |

After editing `notes.md` or `sources.json`, run the build and commit `index.html` with your change:

```bash
python build.py
```

## Transcribing the sources-only entries

```bash
python transcribe.py --dry-run
```

This reports, for each entry with no text, which source would be used and how much text it yields.
Without `--dry-run` it writes that text into `notes.md`, records the sources used under
`transcribed_from` in `sources.json`, and rebuilds the page. The page then shows "Transcribed from …"
under the entry.

How it works:

- It tries each entry's sources best first, preferring the one that lists the changes over a
  downtime notice. It skips previews, wiki compilations and player observations.
- An unnumbered `.X` entry gathers every dated mini-update between the two versions, each under its
  date.
- A section that already has text is never touched unless you pass `--overwrite`.
- `--only 5.2,7.6.2` limits a run to the versions you name.
- Fetched pages are cached in `.cache/`, which is git-ignored. `--refresh` fetches them again.

Six entries have no usable source, so they stay sources-only: 3.4, 3.6, 3.7, 5.7.1, 8.2.3 and 9.2.2.

**Commit before you run it.** Then `git diff notes.md` shows exactly what was added, for review
before you publish. The extraction was tested only in dry runs and with placeholder text, never by
reading its output. So read the diff, especially the older pages, whose HTML is the least regular.

## Linking to a version

Every entry has the id `vu-<version>`, so a link opens that entry and scrolls to it:

- `index.html#vu-5.7` for VU 5.7
- `#vu-7.4.x` for the unnumbered mini-updates after VU 7.4
- `#vu-cot-patch-2` for the unnumbered 2002 patches

`#vu-5.7`, `#5.7`, and `#vu-4` for `#vu-4.0` all work. The `#` beside an entry's title is its
permalink.

## Source ranking

Each source carries a tier, 1 to 5, and the list sorts by tier. Within a tier, previews come last,
then older sources first.

1. **Official**: MindArk's own website, read through the Wayback Machine.
2. **MindArk staff**: posted by a MindArk employee on a forum.
3. **News bot**: the forum's news bot, which reposted MindArk's notices the day they appeared.
4. **Contemporary copy**: copied at the time by a fan site, download portal or player.
5. **Later compilation**: wikis, archives and later reposts. Entropia Museum is here: its early
   entries republish forum threads.

Every source must have a `url`. A source without one is not shown, because a name with no page is
not something a reader can check.

## `sources.json`

```json
{
  "entries": {
    "5.7": {
      "date": "2004-06-01",
      "note": "optional text shown above the notes",
      "sources": [
        {"tier": 2, "label": "Entropia Pioneers forum — PROJECT ENTROPIA VERSION UPDATE 5.7",
         "url": "https://web.archive.org/web/20040629133920/http://...", "date": "2004-06-01"},
        {"tier": 2, "label": "... (preview)", "url": "...", "preview": true}
      ]
    }
  }
}
```

A version in `sources.json` with no section in `notes.md` still gets an entry. It is marked "sources
only" when one of its sources holds the notes, and "no notes found" when none does: every source is a
name with no page, a preview, a wiki compilation or a player's observations.
An entry can also carry `note_until_transcribed`, which is shown only while it has no text. Use it
for anything that stops being true once the notes are in, such as "the notes are in the first source
below".

## Corrections to the original compilation

Three corrections were made against MindArk's own pages when `notes.md` was created from the
original compilation:

- **The text under VU 5.4 was VU 6.4's.** It matched MindArk's 6.4 content list line for line, and
  MindArk's 5.4 content list (17 Dec 2003) contains none of it. The 5.4 section is empty until the
  real notes are transcribed.
- **The text under VU 5.7.1 was VU 7.5.1's.** It opens "The following issues have been addressed
  in the VU 7.5.1 update", so it now sits under 7.5.1.
- **"VU 3.X" (25 Oct 2002) is VU 3.9**, which is MindArk's own name for that patch.

## Copyright

Project Entropia, Entropia Universe and their release notes are the work of MindArk PE AB. This is
an independent preservation project, not affiliated with MindArk.
