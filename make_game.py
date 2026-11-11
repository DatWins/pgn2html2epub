"""
make_game.py  -  turn one tidy PGN into
    * an interactive web page  (live board, clickable moves)      -> out/<name>.html
    * a Kobo-friendly EPUB     (same text, board diagrams)       -> out/<name>.epub

Usage (Windows, in the kit folder):
    py make_game.py games\\my-game.pgn

Needs:  py -m pip install chess pillow
See README.md for setup and PGN_GUIDE.md for how to write the PGN.
"""
import datetime
import html
import io
import json
import re
import sys
import uuid
import zipfile
from pathlib import Path

try:
    import chess
except ImportError:
    sys.exit("python-chess is missing. Run:  py -m pip install chess pillow")
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow is missing. Run:  py -m pip install chess pillow")

KIT = Path(__file__).resolve().parent
ASSETS = KIT / "assets"
esc = lambda s: html.escape(str(s), quote=True)

NAG_SYMBOLS = {1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!"}
# A speaker label: one or more CAPITALISED words followed by a colon, e.g.  MILES:  or  O'KELLY:
SPEAKER = r"[A-Z][A-Z’'\-]+(?: [A-Z][A-Z’'\-]+)*"
SPEAKER_SPLIT = re.compile(rf"(?<![\w’'])(?={SPEAKER}:\s)")
SPEAKER_START = re.compile(rf"^({SPEAKER}):\s*(.*)$", re.S)


# --------------------------------------------------------------------------- reading the PGN
def read_pgn(text):
    tags = dict(re.findall(r'^\[(\w+)\s+"(.*)"\]\s*$', text, re.M))
    movetext = re.sub(r"^\[.*\]\s*$", "", text, flags=re.M)
    toks, i = [], 0
    while i < len(movetext):
        c = movetext[i]
        if c.isspace():
            i += 1
        elif c == "{":
            j = movetext.index("}", i)
            body = re.sub(r"\[%[^\]]*\]", "", movetext[i + 1:j])   # drop Lichess [%clk ..] [%cal ..] codes
            body = re.sub(r"\s+", " ", body).strip()
            if body:
                toks.append(("c", body))
            i = j + 1
        elif c == ";":                                   # rest-of-line comment
            j = movetext.find("\n", i)
            j = len(movetext) if j < 0 else j
            toks.append(("c", movetext[i + 1:j].strip()))
            i = j
        elif c in "()":
            toks.append((c, None))
            i += 1
        else:
            word = re.match(r"[^\s(){};]+", movetext[i:]).group(0)
            i += len(word)
            if re.fullmatch(r"\d+\.+", word):
                continue                                  # move number on its own
            if word in ("1-0", "0-1", "1/2-1/2", "*"):
                toks.append(("r", word))
                continue
            if re.fullmatch(r"\$\d+", word):
                toks.append(("nag", NAG_SYMBOLS.get(int(word[1:]), "")))
                continue
            word = re.sub(r"^\d+\.+", "", word)          # "12.Nf3" / "12...Nf3"
            m = re.fullmatch(r"(.*?)([!?]*)", word)
            toks.append(("m", (m.group(1), m.group(2))))
    return tags, toks


class Tree:
    """Every position in the game and its side lines. Node 'n0' is the start position."""

    def __init__(self, start_fen):
        self.nodes = {}
        self.root = self._add(start_fen, None, None, "")

    def _add(self, fen, parent, move_info, ann):
        nid = f"n{len(self.nodes)}"
        n = {"fen": fen, "parent": parent, "children": [], "san": "", "ann": ann,
             "label": "", "from": "", "to": "", "white": False}
        if move_info:
            san, frm, to, white, number = move_info
            n.update(san=san, white=white, label=f"{number}{'.' if white else '...'}{san}",
                     **{"from": frm, "to": to})
        self.nodes[nid] = n
        if parent:
            self.nodes[parent]["children"].append(nid)
        return nid

    def play(self, at, san, ann):
        board = chess.Board(self.nodes[at]["fen"])
        try:
            move = board.parse_san(san)
        except ValueError:
            return None
        info = (board.san(move), chess.square_name(move.from_square), chess.square_name(move.to_square),
                board.turn == chess.WHITE, board.fullmove_number)
        for c in self.nodes[at]["children"]:              # same move already there -> reuse it
            if self.nodes[c]["san"] == info[0]:
                if ann and not self.nodes[c]["ann"]:
                    self.nodes[c]["ann"] = ann
                return c
        board.push(move)
        return self._add(board.fen(), at, info, ann)

    def text(self, nid):
        n = self.nodes[nid]
        return n["label"] + n["ann"]

    def short(self, nid):
        n = self.nodes[nid]
        return n["san"] + n["ann"]


def build_tree(tags, toks):
    start = tags.get("FEN") if tags.get("SetUp", "1") == "1" and tags.get("FEN") else chess.STARTING_FEN
    tree = Tree(start)
    errors = []
    pos = [0]

    def line(frm):
        els, cur, before_last = [], frm, frm
        while pos[0] < len(toks):
            kind, val = toks[pos[0]]
            pos[0] += 1
            if kind == ")":
                break
            if kind == "c":
                els.append(("c", val))
            elif kind == "r":
                els.append(("r", val))
            elif kind == "nag":
                if els and els[-1][0] == "m" and val:
                    n = tree.nodes[els[-1][1]]
                    n["ann"] = n["ann"] or val
            elif kind == "(":
                els.append(("v", line(before_last)))
            elif kind == "m":
                san, ann = val
                nid = tree.play(cur, san, ann)
                if nid is None:
                    errors.append(f"Illegal or unreadable move '{san}' after {tree.text(cur) or 'the start'}"
                                  f"  (position: {tree.nodes[cur]['fen']})")
                    continue
                before_last, cur = cur, nid
                els.append(("m", nid))
        return els

    main = line(tree.root)
    return tree, main, errors


# --------------------------------------------------------------------------- names and titles
def person(tag):
    """'Miles, Anthony John' -> 'Anthony John Miles'"""
    if not tag or tag == "?":
        return ""
    if "," in tag:
        last, first = [x.strip() for x in tag.split(",", 1)]
        return f"{first} {last}".strip()
    return tag


def surname(tag):
    if not tag or tag == "?":
        return "?"
    return tag.split(",")[0].strip() if "," in tag else tag.split()[-1]


def nice(v):
    return "" if not v or set(v) <= set("?.") else v


# --------------------------------------------------------------------------- page text
class Writer:
    def __init__(self, tree, main, tags, mode):
        self.t, self.main, self.tags, self.mode = tree, main, tags, mode
        self.out, self.toc, self.diagrams = [], [("top", "Introduction")], []
        self.speakers = {}
        self.has_speakers = bool(SPEAKER_SPLIT.search(" ".join(v for k, v in _walk(main) if k == "c")))

    # moves -----------------------------------------------------------------
    def moves(self, ids):
        parts = []
        for k, nid in enumerate(ids):
            txt = self.t.text(nid) if (self.t.nodes[nid]["white"] or k == 0) else self.t.short(nid)
            parts.append(f'<span class="mv">{esc(txt)}</span>' if self.mode == "epub"
                         else f'<a class="mv" data-id="{nid}">{esc(txt)}</a>')
        return " ".join(parts)

    def variation(self, els):
        out, run = [], []

        def flush():
            if run:
                out.append(self.moves(run))
                run.clear()
        for kind, val in els:
            if kind == "m":
                run.append(val)
            elif kind == "c":
                flush()
                out.append(f'<span class="vc">{esc(val)}</span>')
            elif kind == "v":
                flush()
                out.append(f"({self.variation(val)})")
        flush()
        return " ".join(out)

    # comments --------------------------------------------------------------
    def comment(self, text):
        heading = None
        if "##" in text:                                   # { ## Section title }
            text, heading = text.split("##", 1)
            text, heading = text.strip(), heading.strip()
        html_parts = []
        for part in [p.strip() for p in SPEAKER_SPLIT.split(text) if p.strip()]:
            m = SPEAKER_START.match(part)
            if m:
                name = m.group(1)
                cls = self.speakers.setdefault(name, f"sp{len(self.speakers) % 4}")
                html_parts.append(f'<p class="say {cls}"><span class="spk">{esc(name)}</span> {esc(m.group(2))}</p>')
            else:
                html_parts.append(f'<p class="{"narr" if self.has_speakers else "note"}">{esc(part)}</p>')
        return html_parts, heading

    # whole body ------------------------------------------------------------
    def header(self):
        T = self.tags
        kicker = " · ".join(x for x in (nice(T.get("Event")), nice(T.get("Site"))) if x)
        opening = nice(T.get("Opening")) + (f" ({T['ECO']})" if nice(T.get("ECO")) and nice(T.get("Opening")) else "")
        rows = [f"<div><b>White:</b> {esc(person(T.get('White')))}</div>",
                f"<div><b>Black:</b> {esc(person(T.get('Black')))}</div>"]
        if nice(T.get("Date")):
            rows.append(f"<div><b>Date:</b> {esc(T['Date'].replace('.??', ''))}</div>")
        if nice(T.get("Result")) and T.get("Result") != "*":
            rows.append(f"<div><b>Result:</b> {esc(T['Result'])}</div>")
        h = '<header class="art-head" id="top">'
        if kicker:
            h += f'<div class="kicker">{esc(kicker)}</div>'
        h += f"<h1>{esc(title_of(T))}</h1>"
        if opening:
            h += f'<p class="dek">{esc(opening)}</p>'
        h += f'<div class="gamehead">{"".join(rows)}</div>'
        if nice(T.get("Annotator")):
            h += f'<p class="byline">Notes: <span>{esc(T["Annotator"])}</span></p>'
        return h + "</header>"

    def build(self):
        out = self.out
        out.append(self.header())
        out.append('<section id="intro">')
        run, lines, sec = [], [], 0

        def flush_lines():
            if lines:
                out.append('<div class="lines">' + "".join(f'<p class="var">{l}</p>' for l in lines) + "</div>")
                lines.clear()

        def flush_run():
            if not run:
                return
            flush_lines()
            out.append(f'<p class="ml">{self.moves(run)}</p>')
            if self.mode == "epub":
                last = run[-1]
                self.diagrams.append(last)
                out.append(f'<div class="dia"><img src="images/{last}.png" alt="Diagram after {esc(self.t.text(last))}"/>'
                           f'<p class="cap">After {esc(self.t.text(last))}</p></div>')
            run.clear()

        for kind, val in self.main:
            if kind == "m":
                flush_lines()
                run.append(val)
            elif kind == "c":
                flush_run()
                flush_lines()
                parts, heading = self.comment(val)
                out.extend(parts)
                if heading:
                    sid = f"s{sec}"
                    sec += 1
                    out.append(f'</section><section id="{sid}"><h2>{esc(heading)}</h2>')
                    self.toc.append((sid, heading))
            elif kind == "v":
                flush_run()
                lines.append(self.variation(val))
            elif kind == "r":
                flush_run()
                flush_lines()
                out.append(f'<p class="result">{esc(val)}</p>')
        flush_run()
        flush_lines()
        out.append("</section>")
        return "\n".join(out)


def _walk(els):
    for kind, val in els:
        if kind == "v":
            yield from _walk(val)
        else:
            yield kind, val


def title_of(T):
    return nice(T.get("Title")) or f"{surname(T.get('White'))} – {surname(T.get('Black'))}"


# --------------------------------------------------------------------------- web page
def make_html(tree, main, tags, slug):
    w = Writer(tree, main, tags, "html")
    body = w.build()
    table = {nid: [n["fen"], n["parent"], n["children"], n["san"] + n["ann"] if n["san"] else "",
                   n["label"] + n["ann"] if n["label"] else "", n["from"], n["to"], 1 if n["white"] else 0]
             for nid, n in tree.nodes.items()}
    title = title_of(tags)
    full_title = title + (f" · {nice(tags.get('Event'))}" if nice(tags.get("Event")) else "")
    data = (f"const NODES={json.dumps(table, ensure_ascii=False)};"
            f"const ROOTS={json.dumps({tree.root: [title, 'Start position']}, ensure_ascii=False)};"
            f"const FIRST={json.dumps(tree.root)};const SLUG={json.dumps(slug)};")
    toc = "\n".join(f'    <a data-t="{sid}">{esc(t)}</a>' for sid, t in w.toc)
    page = (ASSETS / "template.html").read_text(encoding="utf-8")
    page = page.replace("%%TITLE%%", esc(full_title)).replace("%%TOC%%", toc)
    page = page.replace("<!--BODY-->", body).replace("/*NODES*/", data)
    return page


# --------------------------------------------------------------------------- board pictures
LIGHT, DARK, BORDER, LASTMOVE = (222, 227, 230), (140, 162, 173), (91, 111, 121), (155, 199, 0)
_pieces = {}


def font(size, bold=False):
    names = (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def piece(code, size):
    key = (code, size)
    if key not in _pieces:
        _pieces[key] = Image.open(ASSETS / "pieces" / f"{code}.png").convert("RGBA").resize((size, size), Image.LANCZOS)
    return _pieces[key]


def board_image(fen, frm="", to="", sq=56, coords=True):
    margin = int(sq * 0.45) if coords else 0
    b = 3
    W = margin + 8 * sq + 2 * b + 6
    H = 8 * sq + 2 * b + margin + 4
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    x0, y0 = margin, 2
    d.rectangle([x0, y0, x0 + 8 * sq + 2 * b - 1, y0 + 8 * sq + 2 * b - 1], fill=BORDER)
    board = chess.Board(fen)
    hl = {frm, to} - {""}
    f = font(int(sq * 0.28))
    for r in range(8):
        for c in range(8):
            name = "abcdefgh"[c] + str(8 - r)
            col = DARK if (r + c) % 2 else LIGHT
            if name in hl:
                col = tuple(int(a * 0.55 + b2 * 0.45) for a, b2 in zip(col, LASTMOVE))
            X, Y = x0 + b + c * sq, y0 + b + r * sq
            d.rectangle([X, Y, X + sq - 1, Y + sq - 1], fill=col)
            p = board.piece_at(chess.parse_square(name))
            if p:
                code = ("w" if p.color else "b") + p.symbol().upper()
                img.paste(piece(code, sq), (X, Y), piece(code, sq))
    if coords:
        for r in range(8):
            d.text((margin / 2, y0 + b + r * sq + sq / 2), str(8 - r), fill=(51, 51, 51), font=f, anchor="mm")
        for c in range(8):
            d.text((x0 + b + c * sq + sq / 2, y0 + 8 * sq + 2 * b + margin / 2), "abcdefgh"[c],
                   fill=(51, 51, 51), font=f, anchor="mm")
    return img


def png(img, colours=64):
    buf = io.BytesIO()
    img.convert("RGB").quantize(colours, method=Image.Quantize.MEDIANCUT).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def wrap(d, text, fnt, width):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=fnt) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w_
    return lines + ([cur] if cur else [])


def cover_image(tags, final_fen, final_text):
    W, H = 800, 1200
    img = Image.new("RGB", (W, H), (31, 58, 95))
    d = ImageDraw.Draw(img)
    y = 80
    kicker = " · ".join(x for x in (nice(tags.get("Event")), nice(tags.get("Site"))) if x).upper()
    if kicker:
        for ln in wrap(d, kicker, font(24, True), W - 120):
            d.text((W / 2, y), ln, fill=(201, 216, 240), font=font(24, True), anchor="mm")
            y += 34
    y += 40
    big = font(70, True)
    for ln in wrap(d, title_of(tags), big, W - 100):
        d.text((W / 2, y), ln, fill="white", font=big, anchor="mm")
        y += 84
    sub = " · ".join(x for x in (nice(tags.get("Opening")), nice(tags.get("Result")) if tags.get("Result") != "*" else "") if x)
    if sub:
        y += 10
        for ln in wrap(d, sub, font(30), W - 120):
            d.text((W / 2, y), ln, fill=(227, 236, 251), font=font(30), anchor="mm")
            y += 40
    bimg = board_image(final_fen, sq=62)
    img.paste(bimg, ((W - bimg.width) // 2, max(y + 30, 430)))
    d.text((W / 2, H - 70), f"Final position after {final_text}", fill=(201, 216, 240), font=font(26), anchor="mm")
    return img


# --------------------------------------------------------------------------- EPUB
EPUB_CSS = """
body{font-family:serif;line-height:1.5;margin:0 .4em}
.kicker{font-family:sans-serif;font-size:.75em;font-weight:bold;text-transform:uppercase;color:#555;margin-top:1em}
h1{font-family:sans-serif;font-size:2em;line-height:1.1;margin:.2em 0}
.dek{color:#1f4fa3;font-size:1.2em;margin:.3em 0}
.byline{font-family:sans-serif;font-size:.85em;font-weight:bold}
.byline span{font-weight:normal;color:#555}
h2{font-family:sans-serif;font-size:1.3em;margin:.6em 0 .5em}
p{margin:.5em 0;text-indent:0}
.gamehead{margin:.4em 0 .8em;color:#333;font-family:sans-serif;font-size:.9em}
.gamehead div{margin:.1em 0}
p.ml{font-weight:bold;font-size:1.15em;margin:1em 0 .4em}
p.ml .mv{color:#1f4fa3}
.spk{font-family:sans-serif;font-weight:bold;font-size:.8em;text-transform:uppercase;letter-spacing:.04em}
.sp0 .spk{color:#555}.sp1 .spk{color:#000}.sp2 .spk{color:#1f4fa3}.sp3 .spk{color:#6b3f12}
.narr{font-style:italic;color:#444}
.lines{border-left:3px solid #ccc;padding-left:.8em;margin:.6em 0}
.lines p.var{margin:.2em 0;font-size:.95em;color:#333}
.vc{font-style:italic;color:#555}
p.result{font-weight:bold;font-size:1.2em;text-align:center}
.dia{text-align:center;margin:1em 0;page-break-inside:avoid}
.dia img{width:85%;max-width:430px}
.cap{font-family:sans-serif;font-size:.85em;font-weight:bold;color:#1f4fa3;text-align:center;margin:.2em 0 0}
"""


def xhtml(title, inner):
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">
<head><meta charset="utf-8"/><title>{esc(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
{inner}
</body></html>'''


def make_epub(tree, main, tags, slug, out_path):
    w = Writer(tree, main, tags, "epub")
    body = w.build().replace("<br>", "<br/>")
    head, rest = body.split('<section id="intro">', 1)
    sections = re.findall(r'<section id="(\w+)">(.*?)</section>', '<section id="intro">' + rest, re.S)
    names = dict(w.toc)
    names["intro"] = "Introduction"
    chapters = []
    for i, (sid, inner) in enumerate(sections):
        if sid == "intro":
            inner = head + "\n" + inner
        if inner.strip():
            chapters.append((f"{i + 1:02d}_{sid}.xhtml", names.get(sid, sid), inner))

    final = [v for k, v in main if k == "m"]
    final = final[-1] if final else tree.root
    images = {f"{nid}.png": png(board_image(tree.nodes[nid]["fen"], tree.nodes[nid]["from"], tree.nodes[nid]["to"]))
              for nid in w.diagrams}
    images["cover.png"] = png(cover_image(tags, tree.nodes[final]["fen"], tree.text(final) or "the start"), 128)

    book_title = title_of(tags)
    uid = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "pgn-kit-" + slug))
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    creator = " and ".join(x for x in (person(tags.get("White")), person(tags.get("Black"))) if x)
    manifest = "\n".join(
        f'<item id="img_{Path(x).stem}" href="images/{x}" media-type="image/png"'
        f'{" properties=\"cover-image\"" if x == "cover.png" else ""}/>' for x in sorted(images))
    manifest += "\n" + "\n".join(f'<item id="c{i}" href="{f}" media-type="application/xhtml+xml"/>'
                                 for i, (f, _, _) in enumerate(chapters))
    spine = '<itemref idref="cover"/>' + "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="bookid">{uid}</dc:identifier><dc:title>{esc(book_title)}</dc:title>
<dc:creator>{esc(creator or "Unknown")}</dc:creator><dc:language>en</dc:language>
<meta property="dcterms:modified">{now}</meta><meta name="cover" content="img_cover"/>
</metadata>
<manifest>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
<item id="css" href="style.css" media-type="text/css"/>
<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
{manifest}
</manifest>
<spine toc="ncx">{spine}</spine>
<guide><reference type="cover" title="Cover" href="cover.xhtml"/></guide>
</package>'''
    nav = "\n".join(f'<li><a href="{f}">{esc(t)}</a></li>' for f, t, _ in chapters)
    ncx_points = "".join(f'<navPoint id="np{i}" playOrder="{i}"><navLabel><text>{esc(t)}</text></navLabel>'
                         f'<content src="{f}"/></navPoint>' for i, (f, t, _) in enumerate(chapters, 1))
    with zipfile.ZipFile(out_path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        put = lambda name, data: z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        put("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        put("OEBPS/content.opf", opf)
        put("OEBPS/style.css", EPUB_CSS)
        put("OEBPS/cover.xhtml", xhtml("Cover", '<div style="text-align:center"><img src="images/cover.png" alt="Cover" style="max-width:100%;height:auto"/></div>'))
        put("OEBPS/nav.xhtml", xhtml("Contents", f'<nav epub:type="toc" id="toc"><h2>Contents</h2><ol>\n{nav}\n</ol></nav>'))
        put("OEBPS/toc.ncx", f'<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            f'<head><meta name="dtb:uid" content="{uid}"/></head><docTitle><text>{esc(book_title)}</text></docTitle><navMap>{ncx_points}</navMap></ncx>')
        for f, t, inner in chapters:
            put(f"OEBPS/{f}", xhtml(t, inner))
        for name, data in images.items():
            put(f"OEBPS/images/{name}", data)
    return len(w.diagrams)


# --------------------------------------------------------------------------- main
def main():
    if len(sys.argv) < 2:
        sys.exit("Usage:  py make_game.py path\\to\\game.pgn")
    src = Path(sys.argv[1])
    try:
        text = src.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:                       # saved by Notepad as "ANSI"
        text = src.read_text(encoding="cp1252")
    tags, toks = read_pgn(text)
    tree, mainline, errors = build_tree(tags, toks)
    if errors:
        print("Stopped - fix this move in the PGN first:")
        print("  -", errors[0])
        if len(errors) > 1:
            print(f"  ({len(errors) - 1} more problem(s) after it, often caused by the first one)")
        sys.exit(1)
    slug = re.sub(r"[^a-z0-9]+", "-", src.stem.lower()).strip("-") or "game"
    out = KIT / "out"
    out.mkdir(exist_ok=True)
    (out / f"{slug}.html").write_text(make_html(tree, mainline, tags, slug), encoding="utf-8")
    n = make_epub(tree, mainline, tags, slug, out / f"{slug}.epub")
    moves = len(tree.nodes) - 1
    print(f"OK - {moves} moves checked (main line and side lines), {n} diagrams.")
    print(f"  web page: {out / (slug + '.html')}")
    print(f"  EPUB:     {out / (slug + '.epub')}")


if __name__ == "__main__":
    main()
