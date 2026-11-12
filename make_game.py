"""
make_game.py  -  turn one tidy PGN into
    * an interactive web page  (live board, clickable moves)      -> out/<name>.html
    * a Kobo-friendly EPUB     (same text, board diagrams)       -> out/<name>.epub

Usage (Windows, in the kit folder):
    py make_game.py games\\my-game.pgn
    py make_game.py games\\my-game.pgn --stockfish          (adds Stockfish mistake diagrams)
    py make_game.py games\\my-game.pgn --stockfish "C:\\path\\to\\stockfish.exe" --depth 18

Needs:  py -m pip install chess pillow
See README.md for setup and PGN_GUIDE.md for how to write the PGN.
"""
import datetime
import html
import io
import json
import re
import shutil
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
def read_games(text):
    """Split a PGN file into games (a Lichess study export = one game per chapter)."""
    games, tags, body, in_moves = [], {}, [], False
    for line in text.splitlines():
        m = re.match(r'^\s*\[(\w+)\s+"(.*)"\]\s*$', line)
        if m and (in_moves or not body or not "".join(body).strip()):
            if in_moves:                                  # a new tag block starts the next game
                games.append((tags, tokenize("\n".join(body))))
                tags, body, in_moves = {}, [], False
            tags[m.group(1)] = m.group(2)
        else:
            body.append(line)
            if line.strip():
                in_moves = True
    if tags or "".join(body).strip():
        games.append((tags, tokenize("\n".join(body))))
    return games


def join_wrapped(text):
    """Notepad-style wrapped lines become one paragraph again; deliberate breaks stay:
    blank lines, short lines, lines ending with ':' and list lines (1. / - / *)."""
    out = []
    for para in text.split("\n\n"):
        lines = para.split("\n")
        joined = lines[0]
        for prev, line in zip(lines, lines[1:]):
            keep = len(prev) < 50 or prev.endswith(":") or re.match(r"(\d+[.)]|[-*•])\s", line)
            joined += ("\n" if keep else " ") + line
        out.append(joined)
    return "\n\n".join(out)


def tokenize(movetext):
    toks, i = [], 0
    while i < len(movetext):
        c = movetext[i]
        if c.isspace():
            i += 1
        elif c == "{":
            j = movetext.index("}", i)
            body = re.sub(r"\[%[^\]]*\]", "", movetext[i + 1:j])   # drop Lichess [%clk ..] [%cal ..] codes
            body = re.sub(r"[ \t\r]+", " ", body)
            body = re.sub(r" ?\n ?", "\n", body).strip()            # keep line breaks the author typed
            body = re.sub(r"\n{3,}", "\n\n", body)
            body = join_wrapped(body)
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
        elif movetext.startswith("--", i) or movetext.startswith("Z0", i):   # null move: not supported
            toks.append(("m", ("--", "")))
            i += 2
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
    return toks


class Tree:
    """Every position in the game and its side lines. Node 'n0' is the start position."""

    def __init__(self):
        self.nodes = {}
        self.root = None

    def add_root(self, fen):
        nid = self._add(fen, None, None, "")
        self.root = self.root or nid
        return nid

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


def start_fen(tags):
    fen = tags.get("FEN")
    if fen and tags.get("SetUp", "1") == "1":
        try:
            return chess.Board(fen).fen()
        except ValueError:
            pass
    return chess.STARTING_FEN


def chapter_name(tags, k):
    for key in ("ChapterName",):
        if nice(tags.get(key)):
            return tags[key]
    ev, study = nice(tags.get("Event")), nice(tags.get("StudyName"))
    if study and ev.startswith(study + ":"):
        return ev[len(study) + 1:].strip()
    if nice(tags.get("White")) and nice(tags.get("Black")):
        yr = nice(tags.get("Date"))[:4].strip("?.")
        return f"{surname(tags['White'])} – {surname(tags['Black'])}" + (f", {ev}" if ev else "") + (f" {yr}" if yr else "")
    return ev or f"Game {k}"


def build(games):
    """One move tree for all games. Returns the tree, one list of page elements, and errors."""
    tree, errors, stream = Tree(), [], []
    multi = len(games) > 1
    for k, (tags, toks) in enumerate(games, 1):
        root = tree.add_root(start_fen(tags))
        name = chapter_name(tags, k)
        els, errs = build_line(tree, root, toks)
        errors += [f"{e}  [in '{name}']" if multi else e for e in errs]
        if multi:
            stream.append(("h", (name, root, tags)))
            if tree.nodes[root]["fen"] != chess.STARTING_FEN and any(e[0] == "m" for e in els):
                stream.append(("start", root))
        stream += els
    return tree, stream, errors


def build_line(tree, root, toks):
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

    return line(root), errors


# --------------------------------------------------------------------------- Stockfish (optional)
STOCKFISH_PLACES = [r"C:\stockfish\stockfish-windows-x86-64-universal.exe", r"C:\stockfish\stockfish.exe",
                    r"C:\stockfish\stockfish-windows-x86-64-avx2.exe", r"C:\stockfish\stockfish-windows-x86-64.exe"]


def find_stockfish(given):
    if given:
        return given if Path(given).is_file() else None
    for p in STOCKFISH_PLACES:
        if Path(p).is_file():
            return p
    for folder in (Path(r"C:\stockfish"), KIT / "stockfish"):
        if folder.is_dir():
            exes = sorted(folder.rglob("stockfish*.exe")) or sorted(folder.rglob("stockfish*"))
            exes = [e for e in exes if e.is_file()]
            if exes:
                return str(exes[0])
    return shutil.which("stockfish")


def show_eval(pov):
    s = pov.white()
    if s.is_mate():
        m = s.mate()
        return f"#{m}" if m > 0 else f"-#{-m}"
    return f"{s.score() / 100:+.1f}"


def stockfish_mistakes(tree, main, engine_path, depth=18, threshold=100):
    """Run Stockfish along every main line. A move is marked when it loses about a pawn
    (threshold, in centipawns) or more, unless the player is still clearly winning after it."""
    import chess.engine
    paths, path = [], []
    for kind, val in main + [("h", None)]:           # the main line of each game, as written in the PGN
        if kind == "h":
            if path:
                paths.append([tree.nodes[path[0]]["parent"]] + path)
            path = []
        elif kind == "m":
            path.append(val)
    total = sum(len(p) for p in paths)
    done, ev, flags = 0, {}, {}
    engine = chess.engine.SimpleEngine.popen_uci(engine_path)
    try:
        for path in paths:
            for nid in path:
                if nid not in ev:
                    board = chess.Board(tree.nodes[nid]["fen"])
                    info = engine.analyse(board, chess.engine.Limit(depth=depth))
                    pv = info.get("pv") or []
                    ev[nid] = (info["score"], info["score"].white().score(mate_score=10000), pv[0] if pv else None)
                done += 1
                print(f"\r  Stockfish (depth {depth}): {done}/{total} positions", end="", flush=True)
            for prev, nid in zip(path, path[1:]):
                node = tree.nodes[nid]
                before_pov, before, best = ev[prev]
                after_pov, after, _ = ev[nid]
                white = node["white"]
                loss = (before - after) if white else (after - before)
                still_winning = (after if white else -after) >= 300
                if best is None or loss < threshold or still_winning:
                    continue
                board = chess.Board(tree.nodes[prev]["fen"])
                if chess.square_name(best.from_square) == node["from"] and chess.square_name(best.to_square) == node["to"]:
                    continue
                number = board.fullmove_number
                flags[nid] = {
                    "fen": tree.nodes[prev]["fen"],
                    "best": f"{number}{'.' if white else '...'}{board.san(best)}",
                    "best_sq": (best.from_square, best.to_square),
                    "played_sq": (chess.parse_square(node["from"]), chess.parse_square(node["to"])),
                    "before": show_eval(before_pov), "after": show_eval(after_pov),
                }
    finally:
        engine.quit()
        print()
    return flags


def mistake_svg(info, size=360):
    import chess.svg
    arrows = [chess.svg.Arrow(*info["best_sq"], color="green"), chess.svg.Arrow(*info["played_sq"], color="red")]
    return chess.svg.board(chess.Board(info["fen"]), arrows=arrows, size=size)


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
    def __init__(self, tree, main, tags, mode, n_games=1):
        self.t, self.main, self.tags, self.mode, self.n_games = tree, main, tags, mode, n_games
        self.out, self.toc, self.diagrams = [], [("top", "Introduction" if n_games == 1 else "Overview")], []
        self.speakers = {}
        self.sf_images = []
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
                out.append(f'<span class="vc">{esc(val.replace(chr(10), " "))}</span>')
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
        br = lambda x: esc(x).replace("\n", "<br/>")
        for para in text.split("\n\n"):
            for part in [p.strip() for p in SPEAKER_SPLIT.split(para) if p.strip()]:
                m = SPEAKER_START.match(part)
                if m:
                    name = m.group(1)
                    cls = self.speakers.setdefault(name, f"sp{len(self.speakers) % 4}")
                    html_parts.append(f'<p class="say {cls}"><span class="spk">{esc(name)}</span> {br(m.group(2))}</p>')
                else:
                    html_parts.append(f'<p class="{"narr" if self.has_speakers else "note"}">{br(part)}</p>')
        return html_parts, heading

    # whole body ------------------------------------------------------------
    def header_kicker(self):
        T = self.tags
        if self.n_games > 1:
            kind = "Lichess study" if nice(T.get("StudyName")) else "Collection"
            what = "chapters" if nice(T.get("StudyName")) else "games"
            return f"{kind} · {self.n_games} {what}"
        return " · ".join(x for x in (nice(T.get("Event")), nice(T.get("Site"))) if x)

    def header(self):
        T = self.tags
        if self.n_games > 1:
            kicker = self.header_kicker()
            opening = ""
        else:
            kicker = " · ".join(x for x in (nice(T.get("Event")), nice(T.get("Site"))) if x)
            opening = nice(T.get("Opening")) + (f" ({T['ECO']})" if nice(T.get("ECO")) and nice(T.get("Opening")) else "")
        rows = []
        if self.n_games == 1:
            rows += [f"<div><b>{side}:</b> {esc(person(T.get(side)))}</div>" for side in ("White", "Black") if nice(T.get(side))]
        if nice(T.get("Date")):
            rows.append(f"<div><b>Date:</b> {esc(T['Date'].replace('.??', ''))}</div>")
        if self.n_games == 1 and nice(T.get("Result")) and T.get("Result") != "*":
            rows.append(f"<div><b>Result:</b> {esc(T['Result'])}</div>")
        h = '<header class="art-head" id="top">'
        if kicker:
            h += f'<div class="kicker">{esc(kicker)}</div>'
        h += f"<h1>{esc(title_of(T))}</h1>"
        if opening:
            h += f'<p class="dek">{esc(opening)}</p>'
        if rows:
            h += f'<div class="gamehead">{"".join(rows)}</div>'
        if nice(T.get("Annotator")):
            ann = T["Annotator"]
            if ann.startswith("http"):                        # Lichess gives a profile link
                ann = ann.rstrip("/").rsplit("/", 1)[-1]
            h += f'<p class="byline">Notes: <span>{esc(ann)}</span></p>'
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
            if kind == "h":                                   # a new game / study chapter
                flush_run()
                flush_lines()
                name, root, gt = val
                shown = no_emoji(name) if self.mode == "epub" else name
                sid = f"s{sec}"
                sec += 1
                out.append(f'</section><section id="{sid}"><h2>{esc(shown)}</h2>')
                players = [person(gt.get(x)) for x in ("White", "Black") if nice(gt.get(x))]
                extra = " – ".join(players)
                if nice(gt.get("Result")) and gt.get("Result") != "*" and players:
                    extra += f" · {gt['Result']}"
                if extra:
                    out.append(f'<p class="gamehead">{esc(extra)}</p>')
                self.toc.append((sid, shown))
                continue
            if kind == "start":                               # chapter starts from a set-up position
                flush_run()
                flush_lines()
                fen = self.t.nodes[val]["fen"]
                side = "White" if fen.split()[1] == "w" else "Black"
                if self.mode == "epub":
                    self.diagrams.append(val)
                    out.append(f'<div class="dia"><img src="images/{val}.png" alt="Starting position"/>'
                               f'<p class="cap">Start: {side} to move</p></div>')
                else:
                    out.append(f'<figure class="dia" data-id="{val}"><div class="sb" data-fen="{esc(fen)}"></div>'
                               f'<figcaption>Start: {side} to move</figcaption></figure>')
                continue
            if kind == "m":
                flush_lines()
                run.append(val)
                info = getattr(self.t, "sf", {}).get(val)
                if info:
                    flush_run()
                    played = self.t.text(val)
                    cap = (f'<span class="sfg">Stockfish: {esc(info["best"])}</span> was better ({esc(info["before"])}). '
                           f'<span class="sfr">After {esc(played)}</span>: {esc(info["after"])}.')
                    if self.mode == "epub":
                        self.sf_images.append(val)
                        out.append(f'<div class="dia sf"><img src="images/sf_{val}.svg" alt="Stockfish diagram before {esc(played)}"/>'
                                   f'<p class="cap">{cap}</p></div>')
                    else:
                        out.append(f'<figure class="dia sfcard" data-id="{self.t.nodes[val]["parent"]}">'
                                   f'<div class="sfsvg">{mistake_svg(info)}</div><figcaption>{cap}</figcaption></figure>')
                continue
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
                if val == "*":
                    continue
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
    if nice(T.get("Title")):
        return T["Title"]
    if nice(T.get("StudyName")):
        return T["StudyName"]
    if nice(T.get("White")) and nice(T.get("Black")):
        return f"{surname(T['White'])} – {surname(T['Black'])}"
    return nice(T.get("Event")) or "Chess game"


EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]")


def no_emoji(s):
    """Kobo fonts have no emoji: drop them from EPUB headings."""
    return re.sub(r"\s{2,}", " ", EMOJI.sub("", s)).strip()


# --------------------------------------------------------------------------- web page
def roots_of(tree, main, title):
    """Board heading for every starting position (one per game / chapter)."""
    roots = {tree.root: [title, "Start position"]}
    for kind, val in main:
        if kind == "h":
            name, root, _ = val
            roots[root] = [name, "Start position"]
    return roots


def make_html(tree, main, tags, slug, n_games=1):
    w = Writer(tree, main, tags, "html", n_games)
    body = w.build()
    table = {nid: [n["fen"], n["parent"], n["children"], n["san"] + n["ann"] if n["san"] else "",
                   n["label"] + n["ann"] if n["label"] else "", n["from"], n["to"], 1 if n["white"] else 0]
             for nid, n in tree.nodes.items()}
    title = title_of(tags)
    full_title = title + (f" · {nice(tags.get('Event'))}" if nice(tags.get("Event")) else "")
    data = (f"const NODES={json.dumps(table, ensure_ascii=False)};"
            f"const ROOTS={json.dumps(roots_of(tree, main, title), ensure_ascii=False)};"
            f"const FIRST={json.dumps(tree.root)};const SLUG={json.dumps(slug)};")
    toc = "\n".join(f'    <a data-t="{sid}">{esc(t)}</a>' for sid, t in w.toc)
    page = (ASSETS / "template.html").read_text(encoding="utf-8")
    page = page.replace("%%TITLE%%", esc(full_title)).replace("%%TOC%%", toc)
    page = page.replace("<!--BODY-->", body).replace("/*NODES*/", data)
    if getattr(tree, "sf", None):
        page = page.replace("</head>", SF_CSS + "</head>", 1)
    return page


SF_CSS = """<style>
figure.sfcard{width:auto;max-width:400px}
.sfsvg svg{display:block;width:100%;max-width:360px;height:auto}
figure.sfcard figcaption{font-size:.8em;font-weight:500;color:var(--ink,#222);line-height:1.45}
.sfg{color:#1b7a2e;font-weight:700}.sfr{color:#b00020;font-weight:700}
:root[data-theme="dark"] .sfg{color:#6fd08a}:root[data-theme="dark"] .sfr{color:#ff7b8a}
</style>
"""


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


def cover_image(tags, final_fen, caption, kicker=None):
    W, H = 800, 1200
    img = Image.new("RGB", (W, H), (31, 58, 95))
    d = ImageDraw.Draw(img)
    y = 80
    if kicker is None:
        kicker = " · ".join(x for x in (nice(tags.get("Event")), nice(tags.get("Site"))) if x)
    kicker = no_emoji(kicker).upper()
    if kicker:
        for ln in wrap(d, kicker, font(24, True), W - 120):
            d.text((W / 2, y), ln, fill=(201, 216, 240), font=font(24, True), anchor="mm")
            y += 34
    y += 40
    big = font(70, True)
    for ln in wrap(d, no_emoji(title_of(tags)), big, W - 100):
        d.text((W / 2, y), ln, fill="white", font=big, anchor="mm")
        y += 84
    sub = " · ".join(x for x in (nice(tags.get("Opening")), nice(tags.get("Result")) if tags.get("Result") != "*" else "") if x)
    if kicker and kicker.startswith(("LICHESS STUDY", "COLLECTION")):
        sub = ""
    if sub:
        y += 10
        for ln in wrap(d, sub, font(30), W - 120):
            d.text((W / 2, y), ln, fill=(227, 236, 251), font=font(30), anchor="mm")
            y += 40
    bimg = board_image(final_fen, sq=62)
    img.paste(bimg, ((W - bimg.width) // 2, max(y + 30, 430)))
    d.text((W / 2, H - 70), caption, fill=(201, 216, 240), font=font(26), anchor="mm")
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
.dia.sf .cap{color:#222;font-weight:normal}
.sfg{color:#1b7a2e;font-weight:bold}.sfr{color:#b00020;font-weight:bold}
"""


def xhtml(title, inner):
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">
<head><meta charset="utf-8"/><title>{esc(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
{inner}
</body></html>'''


def make_epub(tree, main, tags, slug, out_path, n_games=1):
    w = Writer(tree, main, tags, "epub", n_games)
    body = w.build().replace("<br>", "<br/>")
    head, rest = body.split('<section id="intro">', 1)
    sections = re.findall(r'<section id="(\w+)">(.*?)</section>', '<section id="intro">' + rest, re.S)
    names = dict(w.toc)
    names["intro"] = names["top"]
    chapters = []
    for i, (sid, inner) in enumerate(sections):
        if sid == "intro":
            inner = head + "\n" + inner
        if inner.strip():
            chapters.append((f"{i + 1:02d}_{sid}.xhtml", names.get(sid, sid), inner))

    images = {f"{nid}.png": png(board_image(tree.nodes[nid]["fen"], tree.nodes[nid]["from"], tree.nodes[nid]["to"]))
              for nid in w.diagrams}
    if n_games == 1:
        final = [v for k, v in main if k == "m"]
        final = final[-1] if final else tree.root
        caption = f"Final position after {tree.text(final)}" if final != tree.root else "Start position"
        cover = cover_image(tags, tree.nodes[final]["fen"], caption)
    else:                                   # a study: show where the first chapter with moves ends
        final, seen = None, False
        for k, v in main:
            if k == "h" and final:
                break
            if k == "m":
                final = v
        final = final or tree.root
        caption = f"After {tree.text(final)}" if final != tree.root else ""
        cover = cover_image(tags, tree.nodes[final]["fen"], caption, Writer(tree, main, tags, "epub", n_games).header_kicker())
    images["cover.png"] = png(cover, 128)

    book_title = title_of(tags)
    uid = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "pgn-kit-" + slug))
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    creator = " and ".join(x for x in (person(tags.get("White")), person(tags.get("Black"))) if x) if n_games == 1 else ""
    if not creator and nice(tags.get("Annotator")):
        creator = tags["Annotator"].rstrip("/").rsplit("/", 1)[-1]
    for nid in w.sf_images:
        images[f"sf_{nid}.svg"] = ('<?xml version="1.0" encoding="utf-8"?>\n' + mistake_svg(tree.sf[nid], 430)).encode("utf-8")
    manifest = "\n".join(
        f'<item id="img_{Path(x).stem}" href="images/{x}" media-type="{"image/svg+xml" if x.endswith(".svg") else "image/png"}"'
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
            f'<head><meta name="dtb:uid" content="{uid}"/></head><docTitle><text>{esc(no_emoji(book_title))}</text></docTitle><navMap>{ncx_points}</navMap></ncx>')
        for f, t, inner in chapters:
            put(f"OEBPS/{f}", xhtml(t, inner))
        for name, data in images.items():
            put(f"OEBPS/images/{name}", data)
    return len(w.diagrams) + len(w.sf_images)


# --------------------------------------------------------------------------- main
def main():
    args, use_sf, sf_path, depth = [], False, None, 18
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--stockfish":
            use_sf = True
            if i + 1 < len(argv) and not argv[i + 1].startswith("--") and not argv[i + 1].lower().endswith(".pgn"):
                sf_path = argv[i + 1]
                i += 1
        elif a == "--depth" and i + 1 < len(argv):
            depth = int(argv[i + 1])
            i += 1
        else:
            args.append(a)
        i += 1
    if not args:
        sys.exit("Usage:  py make_game.py path\\to\\game.pgn   [--stockfish [path\\to\\stockfish.exe]] [--depth 18]")
    src = Path(args[0])
    if not src.is_file():
        print(f"Can't find the file '{src}'.")
        found = list((KIT / "games").glob("*.pgn")) + list(KIT.glob("*.pgn"))
        if found:
            print("PGN files I can see:")
            for name in sorted((KIT / "games").glob("*.pgn")):
                print(f"   games\\{name.name}")
            for name in sorted(KIT.glob("*.pgn")):
                print(f"   {name.name}")
            print("Type one of those names after  py make_game.py")
        else:
            print("There are no .pgn files in the games folder yet. Save your PGN there first,")
            print("then run e.g.:  py make_game.py games\\your-file-name.pgn")
        sys.exit(1)
    try:
        text = src.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:                       # saved by Notepad as "ANSI"
        text = src.read_text(encoding="cp1252")
    games = read_games(text)
    if not games:
        sys.exit("No game found in that file.")
    tree, mainline, errors = build(games)
    tags = dict(games[0][0])
    if len(games) > 1:                      # a study / collection: name it after the study, not chapter 1
        for k in ("Event", "Site", "Opening", "ECO", "Result", "White", "Black", "Date"):
            tags.pop(k, None)
        tags["Date"] = games[0][0].get("Date", "")
    if errors:
        print("Stopped - fix this move in the PGN first:")
        print("  -", errors[0])
        if len(errors) > 1:
            print(f"  ({len(errors) - 1} more problem(s) after it, often caused by the first one)")
        sys.exit(1)
    tree.sf = {}
    if use_sf:
        engine_path = find_stockfish(sf_path)
        if not engine_path:
            print("Can't find Stockfish." + (f" Nothing at '{sf_path}'." if sf_path else ""))
            print('Tell the kit where it is, e.g.:  py make_game.py games\\my_game.pgn --stockfish "C:\\stockfish\\stockfish.exe"')
            sys.exit(1)
        print(f"Running Stockfish ({engine_path}) - this takes a few minutes for a long game...")
        tree.sf = stockfish_mistakes(tree, mainline, engine_path, depth)
        print(f"  {len(tree.sf)} mistake(s) marked with a diagram.")
    slug = re.sub(r"[^a-z0-9_]+", "-", src.stem.lower()).strip("-") or "game"
    out = KIT / "out"
    out.mkdir(exist_ok=True)
    (out / f"{slug}.html").write_text(make_html(tree, mainline, tags, slug, len(games)), encoding="utf-8")
    n = make_epub(tree, mainline, tags, slug, out / f"{slug}.epub", len(games))
    moves = sum(1 for x in tree.nodes.values() if x["parent"])
    what = f"{len(games)} games/chapters, " if len(games) > 1 else ""
    print(f"OK - {what}{moves} moves checked (main line and side lines), {n} diagrams.")
    print(f"  web page: {out / (slug + '.html')}")
    print(f"  EPUB:     {out / (slug + '.epub')}")


if __name__ == "__main__":
    main()
