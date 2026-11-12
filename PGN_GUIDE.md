# How to write the PGN

PGN is plain text. It has **no bold, colours or headings** of its own. The
script decides how things look from a few simple patterns, listed here.
Open `examples\okelly-miles.pgn` in Notepad next to this guide.

## 1. The tag lines at the top

```
[Event "The Master Game"]
[Site "BBC Television"]
[Date "????.??.??"]
[White "O'Kelly de Galway, Alberik"]
[Black "Miles, Anthony John"]
[Result "0-1"]
[ECO "E15"]
[Opening "Queen's Indian Defence"]
[Annotator "Jeremy James, William Hartston (The Master Game)"]
[Title "O'Kelly – Miles"]
```

| Tag | Where it shows |
|---|---|
| `Event`, `Site` | Small capitals line above the title, and on the EPUB cover |
| `White`, `Black` | **White:** / **Black:** lines. Write them `Surname, First names`; they're shown as *First names Surname* |
| `Title` *(optional)* | The big title. Without it the title is `White surname – Black surname`, e.g. *O'Kelly de Galway – Miles*. Use it to shorten names |
| `Opening`, `ECO` | Blue line under the title, and on the cover |
| `Date` | **Date:** line (left out if it's `????.??.??`) |
| `Result` | **Result:** line and the cover |
| `Annotator` | "Notes:" line |
| `FEN` + `SetUp "1"` | Start from a position instead of move 1 |

## 2. Moves

Write moves normally. Move numbers are optional, spacing doesn't matter:

```
1. c4 b6 2. d4 e6
19... e5!
```

`!`, `?`, `!!`, `??`, `!?`, `?!` stay with the move. `$1` – `$6` (what
Lichess and ChessBase export) are turned into the same symbols.

**Main line moves** are shown in **bold blue**. The script groups the moves
between two comments into one line, and in the EPUB puts a diagram after
each group.

## 3. Comments `{ ... }`

Anything inside curly brackets is a comment, shown as a paragraph after the
move it follows.

```
4. g3 { This is a normal comment. }
```

Lichess codes inside comments, like `[%cal Ge5d4]` or `[%clk 0:05:00]`, are
removed automatically.

## 4. Speaker labels (who is talking)

Start the comment with a name in **CAPITALS followed by a colon**:

```
3. Nf3 { MILES: Oh, we're going to transpose into a boring Queen's Indian. }
```

That becomes a bold name tag (**MILES**) in front of the paragraph.
Each new name gets its own tag colour (up to four different colours).

* A second speaker can start in the middle of the same comment; it gets its
  own paragraph:
  `{ Miles opens the game. O'KELLY: Very strong move. }`
* If a game uses speakers anywhere, comments **without** a name are treated
  as the presenter's narration and shown in grey italics.
* If a game has no speakers at all, comments are shown as normal text.
* Write names exactly the same every time (`O'KELLY:` not sometimes `OKELLY:`).

## 5. Side lines `( ... )`

Put an alternative move in round brackets **right after** the move it
replaces (and after that move's comment):

```
3. Nf3 { MILES: ... } ( 3. e4 ) 3... Nf6
```

`(3. e4)` is White's alternative to `3. Nf3`. Side lines can contain their
own moves, comments and side lines:

```
9... O-O ( 9... dxc4 10. bxc4 Bxc4 11. Ne5 Bd5 12. e4 )
```

On the web page side lines are clickable, and at a branch the board offers
"Choose a line". Writing the same first move as the main line, e.g.
`25... Ng4 { ... } ( 25... Ng4 26. Rf1 Ne3+ )`, is fine: it's joined to the
main move, so the board shows 26.Rf1 as a choice after 25...Ng4.

## 6. Section headings (optional)

PGN has no headings, so the kit uses a comment that starts with `##`:

```
19... e5! { ... } { ## The attack } 20. Nb5
```

Each `## Heading` starts a new section on the web page, adds a link in the
**Contents** sidebar, and becomes a chapter in the EPUB table of contents.
Put it just before the move where the section should start. Without any
`##` comments the whole game is one section.

## 7. The end

Finish with the result (`1-0`, `0-1`, `1/2-1/2` or `*`). A comment just
before it, like `{ O'KELLY RESIGNS. }`, is shown before the result.

## 8. Several games in one file (Lichess studies, collections)

A file can hold more than one game, one after another, each starting with
its own `[Tag]` lines. A Lichess study downloaded with *Share & export →
Study PGN* is exactly that: one game per chapter. The kit then makes
**one page and one EPUB for the whole file**:

* Each game or chapter becomes its own section, with a heading and a link in
  **Contents** (a chapter in the EPUB). The heading is the `ChapterName` tag
  for a Lichess study, otherwise `White – Black, Event Year`.
* Chapters that start from a set-up position (`[FEN "..."]` with moves like
  `2... Nc6`) get a starting diagram; click it to load it on the live board.
* The big title is the `StudyName` tag (or add your own `[Title "..."]` to
  the first game).
* Lichess arrows and circles (`[%cal ...]`, `[%csl ...]`) aren't drawn; they're
  removed from the text.
* Emojis in chapter names show on the web page but are left out of the
  EPUB, because Kobo can't display them.

If you'd rather have one page per game, split the file into separate PGN
files and run the kit on each.

## Checklist before running

* Every `{` has a matching `}` and every `(` a matching `)`.
* Side lines come right after the move they replace.
* Speaker names in capitals with a colon, spelled the same each time.
* Save the file as **UTF-8** (Notepad: *Save as* → Encoding *UTF-8*) so
  curly quotes and dashes look right.
