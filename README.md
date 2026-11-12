# PGN → interactive web page + Kobo EPUB

Write one tidy PGN, run one command, and get:

| File | What it is |
|---|---|
| `out/<name>.html` | Interactive web page: live board on the right, every move clickable, side lines, ◀ ▶ keys, A−/A+, Dark mode, Hide board, works on phones |
| `out/<name>.epub` | Kobo e-book: same text, main line in **bold blue**, a board diagram after each group of main-line moves, cover with the final position |

This is the same layout as the O'Kelly – Miles game on my site
(Move By Move Game Analysis).

---

## One-time setup (Windows 11)

1. Python is already installed. Open **Command Prompt** and install the two
   libraries the script needs:

   ```
   py -m pip install chess pillow
   ```

2. Download this repository from https://github.com/DatWins/pgn2html2epub (green **Code** button → **Download ZIP**, then unzip),
   or `git clone` it.

That's all. No Node, no browser tools needed.

## Making a game

1. Write your PGN and save it in the `games` folder, for example
   `games\my-game.pgn` (`my-game` is just an example: use your own file's name
   everywhere below). Type `dir games` to see the names of the files there. See **[PGN_GUIDE.md](PGN_GUIDE.md)** for how to write it.
2. Open the kit folder in File Explorer, click the address bar, type `cmd`
   and press Enter. A Command Prompt opens in the right folder.
3. Run:

   ```
   py make_game.py games\my-game.pgn
   ```

4. You'll see something like:

   ```
   OK - 96 moves checked (main line and side lines), 36 diagrams.
     web page: ...\out\my-game.html
     EPUB:     ...\out\my-game.epub
   ```

   Double-click the `.html` to open it in your browser. Copy the `.epub`
   to your Kobo.

A whole Lichess study (*Share & export → Study PGN*) works too: every
chapter becomes a section of one page and one EPUB.

The file name of the PGN becomes the name of the outputs
(`my-game.pgn` → `my-game.html`, `my-game.epub`).

### If it says "Stopped - fix this move"

Every move, including every side line, is played on a real board. If one is
illegal or mistyped, nothing is written and the script tells you which move
and after which move it happened. Fix it in the PGN and run again. Usually
it's a typo (`Nf6` for `Nd6`) or a side line in the wrong place.

## Try the example

```
py make_game.py examples\okelly-miles.pgn
```

## Putting a game on the website

Copy the two files from `out\` into the site repository
(`essentiallinks\static\game-analysis\`) and add a line to
`content\en\homepage\04-articles.md` under **Move By Move Game Analysis**:

```markdown
**White – Black** — Event, Opening, Result

- [Read online](game-analysis/my-game.html)
- [Download EPUB](game-analysis/my-game.epub)
```

## What's in this folder

| Path | What it does |
|---|---|
| `make_game.py` | The whole converter (reads the PGN, checks every move, writes the web page and the EPUB) |
| `assets/template.html` | The web page design: board, buttons, colours, phone layout. The script fills in the game |
| `assets/pieces/` | The 12 piece pictures used for the EPUB diagrams |
| `examples/` | Sample PGNs |
| `games/` | Put your own PGNs here |
| `out/` | Results appear here (not saved to GitHub) |
| `PGN_GUIDE.md` | How to write the PGN so it comes out right |
| `CLAUDE_SKILL.md` | Notes for Claude, so a future chat can continue this work |
