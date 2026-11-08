#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#   "kokoro==0.9.4",
#   "misaki[en]==0.9.4",
#   "soundfile",
#   "beautifulsoup4",
#   "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
# ]
# ///
"""Generate the audio (read-aloud) version of blog posts with Kokoro TTS.

Reads each opted-in post (front matter `audio: true`) from the *built* site in
_site/, so includes and Markdown are already rendered, and writes:

  assets/audio/posts/<slug>.mp3   the narration
  _data/audio/<slug>.json         duration and chapter timings for the player

A post is regenerated only when its spoken text, the voice or this script's
TEXT_VERSION changes. Run after `jekyll build`, then build again so Jekyll
picks up the new files (deploy.sh does both).

  uv run _tts/generate.py                 # every opted-in post that changed
  uv run _tts/generate.py --post SLUG     # one post (opt-in not required)
  uv run _tts/generate.py --dry-run ...   # print the spoken text, no audio
  uv run _tts/generate.py --force ...     # regenerate even if unchanged

Pronunciation fixes go in _tts/lexicon.tsv.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEXICON = Path(__file__).resolve().parent / "lexicon.tsv"
AUDIO_DIR = ROOT / "assets" / "audio" / "posts"
DATA_DIR = ROOT / "_data" / "audio"

VOICE = "bm_george"  # Kokoro British male
LANG = "b"  # British English
SAMPLE_RATE = 24000
BITRATE = "48k"
# Bump when extraction or normalisation changes, to regenerate every post.
TEXT_VERSION = 3

# Sections at the end of a post that are not worth reading aloud.
STOP_HEADINGS = re.compile(r"^(sources|references|changelog|further reading|footnotes)\b", re.I)

# Silence (seconds) inserted around blocks.
GAP_PARAGRAPH = 0.45
GAP_ITEM = 0.3
GAP_BEFORE_HEADING = 0.7
GAP_AFTER_HEADING = 0.45

CUE_CODE = "The written post shows some code here."
CUE_TABLE = "The written post has a table here."


# --------------------------------------------------------------------------
# Finding posts
# --------------------------------------------------------------------------

def front_matter(md: Path) -> dict:
    text = md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    fm = {}
    if m:
        for line in m.group(1).splitlines():
            k, sep, v = line.partition(":")
            if sep and not line.startswith((" ", "\t", "-")):
                fm[k.strip()] = v.strip().strip("\"'")
    return fm


def find_posts(only: list[str], site: Path) -> list[dict]:
    posts = []
    for md in sorted((ROOT / "_posts").glob("*.md")):
        m = re.match(r"(\d{4})-\d{2}-\d{2}-(.+)\.md$", md.name)
        if not m:
            continue
        year, slug = m.groups()
        fm = front_matter(md)
        if only:
            if slug not in only:
                continue
        elif fm.get("audio", "").lower() != "true":
            continue
        html = site / "blog" / year / slug / "index.html"
        posts.append({"slug": slug, "md": md, "html": html})
    missing = set(only) - {p["slug"] for p in posts}
    if missing:
        sys.exit(f"no such post: {', '.join(sorted(missing))}")
    return posts


# --------------------------------------------------------------------------
# Extracting the spoken text
# --------------------------------------------------------------------------

LINK_OPEN, LINK_CLOSE = "\x01", "\x02"
# Elements that can be read as one block. The player uses the same selector to find them.
BLOCK_SELECTOR = "p, li, h1, h2, h3, h4, h5, h6, summary, dt, dd, figcaption"
SKIP = "script style svg figure img hr .post-toc .cve-chart .mermaid .quote-credit .footnotes sup.footnote-ref".split()
CONTAINERS = {"div", "section", "aside", "details", "blockquote", "ul", "ol", "article", "main"}


def strip_symbols(text: str) -> str:
    """Drop emoji and pictographs (headings start with one), keep maths signs."""
    out = []
    for ch in text:
        if ch in "️‍⃣":
            continue
        if unicodedata.category(ch) == "So":
            continue
        out.append(ch)
    return "".join(out)


def speak_code(s: str) -> str:
    """Make inline code sayable: tcp_v4_rcv() -> "tcp v4 rcv", /proc/cpuinfo -> "slash proc slash cpuinfo"."""
    s = s.strip().replace("()", "")
    s = re.sub(r"(\w)\(([^()]*)\)", r"\1 \2", s)  # setsockopt(IP_OPTIONS)
    s = re.sub(r"~/?", "home ", s)
    s = re.sub(r"<(\w+)>", r" \1 ", s)  # /proc/<pid>/mem -> "proc pid mem"
    s = s.replace("*", " star ")
    s = s.replace("//", " slash slash ")
    s = re.sub(r"(?<=\w)\.(?=\w)", " dot ", s)
    s = re.sub(r"(?<=\w):(?=\w)", " colon ", s)
    s = re.sub(r"\b0x([0-9a-fA-F]+)\b", lambda m: "hex " + " ".join(m[1].upper()), s)  # 0x0f -> hex 0 F
    # SCREAMING_CASE constants read better as words: PR_SET_SPECULATION_CTRL -> pr set speculation ctrl
    s = re.sub(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", lambda m: m[0].lower(), s)
    s = s.replace("/", " slash ").replace("=", " equals ").replace("_", " ").replace(",", ", ")
    s = re.sub(r"(?<![\w-])--?(?=\w)", "dash ", s)  # ss -Mln
    s = re.sub(r"(?<=\w)-(?=\w)", " ", s)  # prefer-align-cpus-by-uncorecache
    s = re.sub(r"(?<!\S)([a-z])(?!\S)", lambda m: m[1].upper(), s)  # tenant-a -> tenant A, not "uh"
    return re.sub(r"\s+", " ", s).strip()


def inline_text(el) -> str:
    """Text of a block element, with link-only citations like "(Verizon · TechTarget)" removed."""
    for code in el.find_all("code"):
        code.replace_with(speak_code(code.get_text()))
    for a in el.find_all("a"):
        a.replace_with(LINK_OPEN + a.get_text() + LINK_CLOSE)
    text = el.get_text()
    citation = rf"\(\s*(?:{LINK_OPEN}[^{LINK_CLOSE}]*{LINK_CLOSE}[\s·,;|/]*)+\)"
    text = re.sub(citation, "", text)
    text = text.replace(LINK_OPEN, "").replace(LINK_CLOSE, "")
    return re.sub(r"\s+", " ", text).strip()


def own_text(el) -> str:
    """The element's text without nested lists, the same text the player walks in the browser."""
    from bs4 import NavigableString
    from bs4.element import PreformattedString

    parts = []
    for s in el.find_all(string=True):
        if not isinstance(s, NavigableString) or isinstance(s, PreformattedString):
            continue  # comments, doctypes and the like are not in textContent
        p, nested = s.parent, False
        while p is not None and p is not el:
            if p.name in ("ul", "ol"):
                nested = True
                break
            p = p.parent
        if not nested:
            parts.append(str(s))
    return "".join(parts)


def extract(html_path: Path) -> tuple[str, list[dict]]:
    """Return (title, blocks). A block is {kind: heading|para|item|cue, text, level?, id?, el?, orig?}.

    `el` is the block's index in #markdown-content's querySelectorAll(BLOCK_SELECTOR),
    taken before anything is removed, so the browser can find the same element.
    `orig` is that element's own text, which word timings are aligned to.
    """
    from bs4 import BeautifulSoup, NavigableString, Tag

    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    title = soup.select_one(".post-title").get_text(strip=True)
    root = soup.select_one("#markdown-content")
    originals = {}
    for i, el in enumerate(root.select(BLOCK_SELECTOR)):
        el["data-tts-i"] = str(i)
        originals[i] = own_text(el)
    for sel in SKIP:
        for el in root.select(sel):
            el.decompose()

    blocks: list[dict] = []
    stop = False

    def add(kind, text, el=None, **extra):
        text = text.strip()
        if not text:
            return
        if kind == "cue" and blocks and blocks[-1]["kind"] == "cue" and blocks[-1]["text"] == text:
            return  # one cue for a run of code blocks
        if el is not None and el.has_attr("data-tts-i"):
            i = int(el["data-tts-i"])
            extra.update(el=i, orig=originals[i])
        blocks.append({"kind": kind, "text": text, **extra})

    def walk(node):
        nonlocal stop
        for child in list(node.children):
            if stop:
                return
            if isinstance(child, NavigableString):
                if child.strip() and node is root:
                    add("para", re.sub(r"\s+", " ", str(child)))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name
            classes = child.get("class") or []
            if re.fullmatch(r"h[1-6]", name):
                text = strip_symbols(child.get_text(" ", strip=True)).strip()
                if STOP_HEADINGS.match(text):
                    stop = True
                    return
                add("heading", text, child, level=int(name[1]), id=child.get("id"))
            elif name == "pre" or "highlighter-rouge" in classes or "highlight" in classes:
                add("cue", CUE_CODE)
            elif name == "table":
                add("cue", CUE_TABLE)
            elif name == "li":
                nested = [c.extract() for c in child.find_all(["ul", "ol"], recursive=False)]
                inner_blocks = child.find_all(["p", "pre", "div"], recursive=False)
                if inner_blocks:  # a "loose" list item: walk its paragraphs
                    walk(child)
                else:
                    add("item", inline_text(child), child)
                for n in nested:
                    walk(n)
            elif name in ("p", "summary", "dt", "dd", "figcaption"):
                add("para", inline_text(child), child)
            elif name in CONTAINERS:
                walk(child)
            elif child.get_text(strip=True):
                add("para", inline_text(child), child)

    walk(root)
    return title, blocks


# --------------------------------------------------------------------------
# Normalising text for speech
# --------------------------------------------------------------------------

def load_lexicon() -> list[tuple[re.Pattern, str]]:
    rules = []
    if LEXICON.exists():
        for line in LEXICON.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            word, tab, say = line.partition("\t")
            if not tab or not word.strip() or not say.strip():
                print(f"tts: warning: {LEXICON.name}: ignoring {line!r} (needs <word><TAB><how to say it>)",
                      file=sys.stderr)
                continue
            rules.append((re.compile(rf"(?<![\w-]){re.escape(word.strip())}(?![\w])"), say.strip()))
    return rules


def normalise(text: str, lexicon) -> str:
    text = strip_symbols(text)
    text = re.sub(r"https?://\S+", "", text)
    for pattern, say in lexicon:
        text = pattern.sub(say, text)
    # Numbers and symbols
    text = re.sub(r"(\d)\s*×", r"\1 times", text)
    text = re.sub(r"\b([a-zA-Z])\s*×", r"\1 times", text)
    text = text.replace("×", " times ")
    text = text.replace("÷", " divided by ")
    text = text.replace("≈", " about ").replace("~", " about ")
    text = text.replace("≥", " at least ").replace("≤", " at most ")
    text = text.replace("→", " to ").replace("←", " from ")
    text = re.sub(r"(\d)\s*–\s*(?=[$\d])", r"\1 to ", text)  # 2021–2023, 22–26%
    text = re.sub(r"−\s*(?=\d)", "minus ", text)
    text = re.sub(r"(?<![\w$])\+(?=\d)", "plus ", text)
    text = re.sub(r"\b(\d{1,2}):(\d{2})\s*([ap])m\b", lambda m: f"{m[1]}:{m[2]} {m[3].upper()}.M.", text)
    text = re.sub(r"\b(\d+):(\d+)\b(?!\s*[AP]\.M\.)", r"\1 to \2", text)  # ratios like 1:50
    text = re.sub(r"(?<=[A-Za-z0-9])/(?=[A-Za-z])", " or ", text)  # FIDO2/passkeys
    # Abbreviations
    text = re.sub(r"\be\.g\.,?", "for example,", text)
    text = re.sub(r"\bi\.e\.,?", "that is,", text)
    text = re.sub(r"\betc\.", "et cetera.", text)
    text = re.sub(r"\bvs\.?\s", "versus ", text)
    # Markdown leftovers and typography
    text = text.replace("·", ",").replace("|", ",")
    text = text.replace("_", " ")
    text = re.sub(r"(?<=[A-Za-z])\+(?=[A-Z])", " plus ", text)  # Flush+Reload
    text = re.sub(r"[`*#]", "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def spoken_blocks(title: str, blocks: list[dict]) -> list[dict]:
    lexicon = load_lexicon()
    out = [{"kind": "heading", "text": normalise(title, lexicon) + ".", "level": 1, "id": None, "title": title,
            "el": -1, "orig": title},  # -1: the page's .post-title, outside #markdown-content
           {"kind": "para", "text": normalise("By Ishwor Gurung.", lexicon)}]
    for b in blocks:
        text = normalise(b["text"], lexicon)
        if not re.search(r"\w", text):
            continue
        if b["kind"] == "heading" and not text.endswith((".", "?", "!")):
            text += "."
        out.append({**b, "text": text, "title": b["text"]})
    return out


# --------------------------------------------------------------------------
# Synthesis
# --------------------------------------------------------------------------

def silence(seconds: float):
    import numpy as np
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


def word_key(w: str) -> str:
    return re.sub(r"[\W_]+", "", w.lower())


def align(orig: str, spoken: list[tuple[str, float]]) -> list[tuple[float, int]]:
    """Map spoken words (with start times) onto the words of the page text.

    Returns (start time, index into orig.split()) pairs. The two differ where the
    text was normalised ("10×" -> "10 times", lexicon entries) or trimmed (citations),
    so a diff lines them up; page words that were never spoken get no time.
    """
    import difflib

    words = orig.split()
    a_idx = [i for i, w in enumerate(words) if word_key(w)]
    a = [word_key(words[i]) for i in a_idx]
    b = [w for w, _ in spoken]
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out += [(spoken[j1 + k][1], a_idx[i1 + k]) for k in range(i2 - i1)]
        elif tag == "replace":  # spread the page words over the spoken ones
            n, m = i2 - i1, j2 - j1
            out += [(spoken[j1 + (k * m) // n][1], a_idx[i1 + k]) for k in range(n)]
    return out


def synthesise(pipeline, blocks: list[dict]):
    """Return (audio, chapters, words).

    Chapters mark each h2/h3 with its start time. Words list, per page element read,
    when each of its words is spoken, for the player's word highlighting.
    """
    import numpy as np

    parts, chapters, words, t = [], [], [], 0.0
    for i, b in enumerate(blocks):
        if b["kind"] == "heading" and i > 0:
            parts.append(silence(GAP_BEFORE_HEADING))
            t += GAP_BEFORE_HEADING
        if b["kind"] == "heading" and (b["level"] in (2, 3) or i == 0):
            chapters.append({"t": round(t, 2), "title": b["title"] if i else "Introduction",
                             "id": b.get("id"), "level": b["level"] if i else 2})
        spoken = []
        for result in pipeline(b["text"], voice=VOICE, speed=1.0, split_pattern=r"\n+"):
            a = result.audio.numpy() if hasattr(result.audio, "numpy") else np.asarray(result.audio)
            for tok in result.tokens or []:
                if tok.start_ts is not None and word_key(tok.text):
                    spoken.append((word_key(tok.text), t + tok.start_ts))
            parts.append(a.astype(np.float32))
            t += len(a) / SAMPLE_RATE
        if "el" in b and spoken:
            pairs = align(b["orig"], spoken)
            if pairs:
                words.append({
                    "el": b["el"],
                    "fp": " ".join(b["orig"].split())[:40],  # lets the player check it found the right element
                    "end": round(t * 100),
                    "w": [x for tt, wi in pairs for x in (round(tt * 100), wi)],  # centiseconds, word index
                })
        gap = {"heading": GAP_AFTER_HEADING, "item": GAP_ITEM}.get(b["kind"], GAP_PARAGRAPH)
        parts.append(silence(gap))
        t += gap
    return np.concatenate(parts), chapters, words


def encode_mp3(audio, out: Path, title: str):
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.mp3")
    cmd = ["ffmpeg", "-loglevel", "error", "-y",
           "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "-",
           "-c:a", "libmp3lame", "-b:a", BITRATE,
           "-metadata", f"title={title}", "-metadata", "artist=Ishwor Gurung",
           "-metadata", "comment=Read by Kokoro TTS (bm_george)", str(tmp)]
    subprocess.run(cmd, input=audio.tobytes(), check=True)
    tmp.replace(out)


def prune(keep: set[str]):
    """Delete audio for posts that are gone or no longer have `audio: true`."""
    for meta in sorted(DATA_DIR.glob("*.json")):
        slug = meta.stem
        if slug in keep:
            continue
        for f in (meta, AUDIO_DIR / f"{slug}.mp3", AUDIO_DIR / f"{slug}.words.json"):
            f.unlink(missing_ok=True)
        print(f"tts: {slug}: removed (post is gone or no longer has `audio: true`)")


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--post", action="append", default=[], metavar="SLUG", help="only this post (repeatable)")
    ap.add_argument("--force", action="store_true", help="regenerate even if unchanged")
    ap.add_argument("--dry-run", action="store_true", help="print the spoken text and exit")
    ap.add_argument("--site", type=Path, default=ROOT / "_site",
                    help="built site to read posts from (default: _site)")
    args = ap.parse_args()

    posts = find_posts(args.post, args.site.resolve())
    if not args.post and not args.dry_run:
        prune({p["slug"] for p in posts})
    if not posts:
        print("tts: no posts have `audio: true` in their front matter")
        return

    pipeline = None
    for post in posts:
        slug = post["slug"]
        if not post["html"].exists():
            sys.exit(f"tts: {post['html']} not found; run `bundle exec jekyll build` first")
        title, blocks = extract(post["html"])
        blocks = spoken_blocks(title, blocks)

        if args.dry_run:
            print(f"===== {slug}")
            for b in blocks:
                prefix = {"heading": "\n## ", "item": "  - ", "cue": "  [cue] "}.get(b["kind"], "")
                print(prefix + b["text"])
            continue

        digest = hashlib.sha256(json.dumps([TEXT_VERSION, VOICE, BITRATE, blocks]).encode()).hexdigest()[:16]
        mp3 = AUDIO_DIR / f"{slug}.mp3"
        words_path = AUDIO_DIR / f"{slug}.words.json"
        meta_path = DATA_DIR / f"{slug}.json"
        if not args.force and mp3.exists() and words_path.exists() and meta_path.exists():
            if json.loads(meta_path.read_text()).get("hash") == digest:
                print(f"tts: {slug}: unchanged")
                continue

        if pipeline is None:
            # Kokoro's bundled espeak-ng data is broken on some systems; prefer the system copy.
            for data in ("/usr/share/espeak-ng-data", "/usr/lib/x86_64-linux-gnu/espeak-ng-data"):
                if Path(data).is_dir():
                    os.environ.setdefault("ESPEAK_DATA_PATH", data)
                    break
            import warnings
            warnings.filterwarnings("ignore")
            from kokoro import KPipeline
            pipeline = KPipeline(lang_code=LANG, repo_id="hexgrad/Kokoro-82M")

        words = sum(len(b["text"].split()) for b in blocks)
        print(f"tts: {slug}: synthesising {words} words...", flush=True)
        started = time.time()
        audio, chapters, words = synthesise(pipeline, blocks)
        duration = len(audio) / SAMPLE_RATE
        encode_mp3(audio, mp3, title)
        words_path.write_text(json.dumps({"selector": BLOCK_SELECTOR, "blocks": words}, separators=(",", ":")),
                              encoding="utf-8")

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        meta = {
            "src": f"/assets/audio/posts/{slug}.mp3",
            "words": f"/assets/audio/posts/{slug}.words.json",
            "duration": round(duration, 1),
            "bytes": mp3.stat().st_size,
            "voice": f"Kokoro {VOICE}",
            "hash": digest,
            "chapters": chapters,
        }
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"tts: {slug}: {duration / 60:.1f} min, {mp3.stat().st_size / 1e6:.1f} MB "
              f"in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
