---
name: pgn-to-interactive-html-epub
description: Use when the user sends a PGN, Lichess study, annotated game or chess article/PDF to turn into an interactive HTML page (live board, clickable moves) plus a Kobo EPUB.
---

# PGN / chess article → interactive HTML + EPUB

Notes for Claude. The user reads chess on a big monitor (interactive HTML)
and on a Kobo (EPUB), for eyesight. Every game or article gets BOTH outputs,
plus (when the source is not already a PGN) a clean "tidy" PGN.

## Use this kit first

This repository is the working tool. For a single game:

```
pip install chess pillow        # in a cloud session where PyPI is blocked:
                                # git clone --depth 1 -b v1.11.2 https://github.com/niklasf/python-chess
                                # and set PYTHONPATH to it
python make_game.py games/<name>.pgn   ->  out/<name>.html + out/<name>.epub
```

Pure Python (python-chess + Pillow) so it also runs on the user's Windows 11 PC
(`py make_game.py games\<name>.pgn`). The user is learning PGN and Python and
wants to run this themselves — explain in plain steps, Windows commands.

**Do not invent content.** Headings, titles and labels come only from the PGN
(`## Heading` comments, `[Title]` tag, `NAME:` speaker prefixes). If something
would help (section headings, a shorter title), suggest the PGN line to add
rather than hard-coding it in the script. Earlier, made-up section headings
were added to O'Kelly – Miles without saying so, and the user noticed.

## PGN conventions the kit understands (details in PGN_GUIDE.md)
- Tags: Event, Site, Date, White/Black ("Surname, First"), Result, ECO,
  Opening, Annotator, optional Title, FEN+SetUp.
- `{ NAME: text }` → bold speaker tag (colour per speaker); if any speakers,
  unlabelled comments = grey italic narration.
- `{ ## Heading }` → new section + Contents entry + EPUB chapter.
- `( ... )` side lines right after the move they replace; a side line that
  repeats the main move is merged into it (board then offers "Choose a line").
- `$1..$6` → ! ? !! ?? !? ?!. Lichess `[%cal]`, `[%csl]`, `[%clk]` codes are stripped.
- Every move incl. variations is replayed; any illegal move stops the build.
- Several games in one file (Lichess study export = one game per chapter):
  one page/EPUB, each game a section (ChapterName or White – Black), a
  clickable start diagram for FEN chapters, title from StudyName/Title,
  "Overview" for the header section, emojis stripped in the EPUB only.

## Optional Stockfish mode (`--stockfish [path] [--depth 18]`)
- Analyses each game's written main line (one engine call per position).
  A move is marked when it loses ≥100 cp for the mover and the mover isn't
  still ≥+3 after it, and Stockfish's best move differs.
- Marked moves get a python-chess `chess.svg.board` of the position before
  the move, green arrow = best, red = played, caption
  "Stockfish: X was better (eval). After Y: eval." Inline SVG on the page
  (clickable, loads the position); separate .svg images in the EPUB.
- The user likes this board style (from their analyze_game.py chat).
- Default engine search: C:\stockfish\*.exe, then PATH.
- Comment line breaks: wrapped lines are re-joined; blank lines, short
  lines, lines ending ':' and list lines keep their break.

## Web page design (assets/template.html — keep it)
- Sticky top bar: title, A− / A+, Dark (saved in localStorage, try/catch),
  Hide board (phones).
- Desktop: Contents sidebar left, text centre (Georgia serif 21px, line-height
  1.6, max ~44em), live board RIGHT (sticky). Phones: compact board pinned on
  top; sideways phones: board left, text right.
- Main-line moves bold blue (`#1f4fa3`) in their own paragraph; side-line
  moves grey with dotted underline; current move highlighted yellow
  (`#ffe08a`) and scrolled into view.
- Board: flat blue-grey squares (light `#dee3e6`, dark `#8ca2ad`, border
  `#5b6f79`), cburnett pieces as data URIs, coordinates outside the board,
  last-move highlight.
- Controls ⏮ ◀ ▶ ⏭ ⇅ and keys ←/→/Home/End/F; "Choose a line" at branches;
  move path under the board; click a piece then a square to try own moves.
- Template placeholders: `%%TITLE%%`, `%%TOC%%`, `<!--BODY-->`, `/*NODES*/`.
  NODES row: `[fen, parent, children[], san+ann, label+ann, from, to, white]`.

## EPUB design
- Same text, main line bold blue, big readable serif.
- Board diagram (Pillow, same colours) after each group of main-line moves,
  caption "After 19...e5!"; cover = Event/Site, title, opening · result,
  final position. EPUB 3 + NCX, mimetype first and uncompressed.

## When the source is a PDF/article, not a PGN
- Extract text (pdftotext -layout) and diagrams (pdfimages); rebuild the start
  FEN from diagrams; write a tidy PGN (one move pair per line, wrapped
  comments, indented variations); replay every move; then run the kit.
- A PGN can't branch after the last move: post-game analysis becomes
  side lines on the final move.

## Test and deliver
- Open the HTML at 1680×1000, 390×844 and 844×390: no console errors, every
  `a.mv` resolves, no sideways scrolling on phones. Unzip the EPUB, check
  XML parses, look at the cover and a diagram.
- Public site: DatWins/essentiallinks → `static/game-analysis/` + entry under
  "Move By Move Game Analysis" in `content/en/homepage/04-articles.md`.
- Copyrighted books stay private; the user decides what goes public.
