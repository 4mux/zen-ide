# Vim Mode Command Reference

**Created_at:** 2026-03-22  
**Updated_at:** 2026-03-22  
**Status:** Active  
**Goal:** Complete reference of all vim commands available in Zen IDE  
**Scope:** `src/editor/vim_mode.py`, `src/editor/vim_command_router.py`  

---

## Overview

Zen IDE includes a full vim modal editing experience powered by GtkSourceView's native `VimIMContext`. This reference covers every mode, motion, operator, text object, and ex-command available.

> **Enable/Disable:** Settings → `behavior.is_nvim_emulation_enabled`

---

## Modes

| Mode | Status Bar | How to Enter | Description |
|------|-----------|--------------|-------------|
| **Normal** | `NORMAL` (green) | `Escape` or `Ctrl+[` | Default mode — navigate and compose commands |
| **Insert** | `INSERT` (blue) | `i`, `a`, `o`, `I`, `A`, `O`, `s`, `S`, `C` | Type text freely |
| **Visual** | `VISUAL` (orange) | `v` | Select characters |
| **Visual Line** | `V-LINE` (orange) | `V` (Shift+V) | Select whole lines |
| **Visual Block** | `V-BLOCK` (orange) | `Ctrl+V` | Select rectangular blocks |
| **Replace** | `REPLACE` (red) | `R` | Overwrite existing text |
| **Command** | `COMMAND` (purple) | `:` | Enter ex-commands |
| **Search** | `SEARCH` (purple) | `/` or `?` | Search forward or backward |

---

## Normal Mode

### Cursor Movement

| Key | Action |
|-----|--------|
| `h` | Move left |
| `j` | Move down |
| `k` | Move up |
| `l` | Move right |
| `w` | Next word start |
| `W` | Next WORD start (whitespace-delimited) |
| `b` | Previous word start |
| `B` | Previous WORD start |
| `e` | Next word end |
| `E` | Next WORD end |
| `0` | Start of line |
| `^` | First non-blank character |
| `$` | End of line |
| `gg` | First line of file |
| `G` | Last line of file |
| `{number}G` | Go to line number |
| `{` | Previous blank line (paragraph up) |
| `}` | Next blank line (paragraph down) |
| `(` | Previous sentence |
| `)` | Next sentence |
| `%` | Matching bracket `()`, `[]`, `{}` |
| `f{char}` | Jump to next `char` on current line |
| `F{char}` | Jump to previous `char` on current line |
| `t{char}` | Jump to before next `char` on current line |
| `T{char}` | Jump to after previous `char` on current line |
| `;` | Repeat last `f`/`F`/`t`/`T` |
| `,` | Repeat last `f`/`F`/`t`/`T` in reverse |
| `H` | Top of visible screen |
| `M` | Middle of visible screen |
| `L` | Bottom of visible screen |
| `Ctrl+D` | Scroll half page down |
| `Ctrl+U` | Scroll half page up |
| `Ctrl+F` | Scroll full page down |
| `Ctrl+B` | Scroll full page up |
| `Ctrl+E` | Scroll one line down |
| `Ctrl+Y` | Scroll one line up |

### Entering Insert Mode

| Key | Action |
|-----|--------|
| `i` | Insert before cursor |
| `I` | Insert at start of line |
| `a` | Append after cursor |
| `A` | Append at end of line |
| `o` | Open new line below |
| `O` | Open new line above |
| `s` | Substitute character (delete + insert) |
| `S` | Substitute entire line |
| `C` | Change to end of line |
| `R` | Enter Replace mode |

### Operators

Operators can be combined with motions and counts: `{operator}[count]{motion}`

| Operator | Action | Example |
|----------|--------|---------|
| `d` | Delete | `dw` delete word, `dd` delete line, `d$` delete to end |
| `c` | Change (delete + insert) | `cw` change word, `cc` change line, `ci"` change inside quotes |
| `y` | Yank (copy) | `yw` yank word, `yy` yank line, `y$` yank to end |
| `>` | Indent right | `>>` indent line, `>}` indent paragraph |
| `<` | Indent left | `<<` unindent line, `<}` unindent paragraph |
| `=` | Auto-indent | `==` auto-indent line, `=G` indent to end of file |
| `~` | Toggle case | `~` toggle char, `g~w` toggle word |
| `gu` | Lowercase | `guw` lowercase word, `guu` lowercase line |
| `gU` | Uppercase | `gUw` uppercase word, `gUU` uppercase line |
| `gq` | Format/wrap text | `gqq` format line, `gq}` format paragraph |

### Text Objects

Used with operators: `{operator}{a/i}{object}`

- `a` = "a" (includes surrounding delimiter)
- `i` = "inner" (contents only, excludes delimiter)

| Object | Description | Example |
|--------|-------------|---------|
| `w` | Word | `diw` delete inner word, `daw` delete a word |
| `W` | WORD (whitespace-delimited) | `diW`, `daW` |
| `s` | Sentence | `dis`, `das` |
| `p` | Paragraph | `dip`, `dap` |
| `"` | Double quotes | `ci"` change inside quotes |
| `'` | Single quotes | `ci'` change inside single quotes |
| `` ` `` | Backticks | `` ci` `` change inside backticks |
| `(` or `)` | Parentheses | `di(` delete inside parens |
| `[` or `]` | Brackets | `da]` delete including brackets |
| `{` or `}` | Braces | `ci{` change inside braces |
| `<` or `>` | Angle brackets | `dit` delete inside angle brackets |
| `t` | XML/HTML tag | `cit` change tag contents |

### Editing

| Key | Action |
|-----|--------|
| `x` | Delete character under cursor |
| `X` | Delete character before cursor |
| `r{char}` | Replace character under cursor with `char` |
| `J` | Join current line with next |
| `u` | Undo |
| `Ctrl+R` | Redo |
| `.` | Repeat last change |
| `p` | Paste after cursor |
| `P` | Paste before cursor |
| `~` | Toggle case of character |
| `Ctrl+A` | Increment number under cursor |
| `Ctrl+X` | Decrement number under cursor |

### Counts

Most commands accept a count prefix:

| Example | Action |
|---------|--------|
| `3w` | Move 3 words forward |
| `5dd` | Delete 5 lines |
| `2dw` | Delete 2 words |
| `10j` | Move 10 lines down |
| `3p` | Paste 3 times |

### Registers

| Key | Action |
|-----|--------|
| `"a`–`"z` | Named registers (e.g., `"ayw` yank word into register `a`) |
| `""` | Unnamed register (default) |
| `"0` | Last yank register |
| `"1`–`"9` | Delete history registers |
| `"+` | System clipboard |
| `"*` | Primary selection (X11) |

### Marks

| Key | Action |
|-----|--------|
| `m{a-z}` | Set mark at cursor position |
| `` `{a-z} `` | Jump to mark (exact position) |
| `'{a-z}` | Jump to mark (line start) |
| ` `` ` | Jump to position before last jump |
| `'.` | Jump to last change |

### Macros

| Key | Action |
|-----|--------|
| `q{a-z}` | Start recording macro into register |
| `q` | Stop recording |
| `@{a-z}` | Play macro from register |
| `@@` | Replay last macro |
| `{count}@{a-z}` | Play macro `count` times |

---

## Visual Mode

Enter with `v` (character), `V` (line), or `Ctrl+V` (block).

| Key | Action |
|-----|--------|
| `v` / `V` / `Ctrl+V` | Switch visual sub-mode |
| `o` | Move to other end of selection |
| `d` or `x` | Delete selection |
| `c` or `s` | Change selection |
| `y` | Yank selection |
| `>` | Indent selection |
| `<` | Unindent selection |
| `~` | Toggle case |
| `u` | Lowercase |
| `U` | Uppercase |
| `J` | Join selected lines |
| `gq` | Format selection |
| `Escape` | Return to Normal mode |

### Visual Block (`Ctrl+V`)

| Key | Action |
|-----|--------|
| `I` | Insert at start of each line in block |
| `A` | Append at end of each line in block |
| `c` | Change each line in block |
| `r{char}` | Replace all characters in block |

---

## Search

| Key | Action |
|-----|--------|
| `/{pattern}` | Search forward |
| `?{pattern}` | Search backward |
| `n` | Next match (same direction) |
| `N` | Next match (opposite direction) |
| `*` | Search forward for word under cursor |
| `#` | Search backward for word under cursor |

---

## Ex-Commands (`:` Command Line)

### Zen IDE Commands

These commands are routed to Zen IDE actions:

| Command | Action |
|---------|--------|
| `:w` | Save current file |
| `:q` | Close current tab |
| `:q!` | Close tab without saving |
| `:wq` or `:x` | Save and close tab |
| `:wq!` or `:x!` | Save and force close |
| `:e {path}` | Open file (creates if needed) |
| `:tabnew` | New empty tab |
| `:tabnew {path}` | Open file in new tab |
| `:tabnext` / `:tabn` | Next tab |
| `:tabprev` / `:tabp` | Previous tab |
| `:noh` / `:nohlsearch` | Clear search highlights |

### Built-in Ex-Commands

These are handled natively by VimIMContext:

| Command | Action |
|---------|--------|
| `:{number}` | Go to line number |
| `:%s/old/new/g` | Replace all occurrences in file |
| `:s/old/new/g` | Replace all on current line |
| `:%s/old/new/gc` | Replace with confirmation |
| `:set {option}` | Set a vim option |
| `:set number` | Show line numbers |
| `:set nonumber` | Hide line numbers |
| `:set wrap` | Enable word wrap |
| `:set nowrap` | Disable word wrap |
| `:!{command}` | Execute shell command |
| `:r {file}` | Read file contents into buffer |
| `:r !{command}` | Read command output into buffer |

### Substitution Flags

| Flag | Meaning |
|------|---------|
| `g` | Replace all occurrences on line (not just first) |
| `c` | Ask for confirmation |
| `i` | Case-insensitive |
| `I` | Case-sensitive |

---

## Zen Shortcuts Preserved in Vim Mode

These Zen IDE shortcuts always work regardless of vim mode:

| Shortcut | Action |
|----------|--------|
| `Cmd+S` / `Ctrl+S` | Save file |
| `Cmd+P` / `Ctrl+P` | Quick open |
| `Cmd+Shift+P` | Command palette |
| `Cmd+Shift+F` | Global search |
| `Cmd+W` / `Ctrl+W` | Close tab |
| `Cmd+Q` / `Ctrl+Q` | Quit |
| `Cmd+,` | Settings |
| `Cmd+.` | Toggle Dev Pad |

---

## Quick Reference Card

```
MOVEMENT          EDITING           COMMANDS
h j k l  ←↓↑→    i   insert        :w   save
w b e    words    a   append        :q   close
0 ^ $    line     o   line below    :wq  save+close
gg G     file     dd  delete line   :e   open file
{ }      para     yy  yank line     /    search
f t      find     p   paste         :s   substitute
% ( )    match    u   undo
H M L    screen   .   repeat        VISUAL
Ctrl+D/U scroll   c   change        v    character
                  >   indent        V    line
OBJECTS           <   unindent      ^V   block
iw aw    word     r   replace
i" a"    quotes   ~   toggle case
i( a(    parens
i{ a{    braces   MACROS
it at    tags     qa  record to a
                  q   stop
                  @a  play a
```
