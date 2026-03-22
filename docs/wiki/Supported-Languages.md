# Supported Languages

Zen IDE has deep, first-class support for **Python**, **JavaScript**, and **Terraform**. Every supported language gets the same four core capabilities — and the goal is to keep extending this list over time.

---

## Core Capabilities

Every fully supported language provides the following four features:

### Syntax Highlighting
Powered by **GtkSourceView 5** and its built-in language definition library. Zen IDE extends this with additional `.lang` files for languages not covered by the standard distribution (e.g. Clojure). Highlighting is applied as you type with no latency penalty.

> **Coming soon:** [Tree-sitter](https://tree-sitter.github.io/) integration will replace regex-based grammar parsing with a proper incremental AST, delivering more accurate and resilient highlighting across all languages.

### Code Navigation
Jump to any symbol definition with **Cmd+Click**. Navigation is implemented using **custom regex-based parsing** that resolves function definitions, class declarations, imports, and resource blocks without requiring an external language server.

### Autocompletion
As you type, Zen suggests completions drawn from the current file's symbol index and language-specific knowledge. This is also built on **custom regex and AST heuristics** rather than an LSP, keeping startup fast and dependencies minimal.

### Debugger
> **Coming soon.** Debugger support (breakpoints, step through, variable inspection) is planned for all supported languages via a DAP (Debug Adapter Protocol) integration.

---

## Supported Languages

### Python (`.py`)

| Capability | Status | Notes |
|---|---|---|
| Syntax highlighting | ✅ | GtkSourceView built-in + semantic layer |
| Code navigation | ✅ | AST + regex, Cmd+Click to definition |
| Autocompletion | ✅ | AST-based + introspection |
| Linting / diagnostics | ✅ | `ruff check` by default |
| Format on save | ✅ | `ruff format` by default |
| Debugger | 🔜 | Planned |

**Default linter:** `ruff`. Configurable in `~/.zen_ide/settings.json` under `diagnostics` — swap in `mypy`, `pylint`, or any tool that writes to stdout. See [Settings Reference](Settings).

### JavaScript / TypeScript (`.js`, `.jsx`, `.ts`, `.tsx`)

| Capability | Status | Notes |
|---|---|---|
| Syntax highlighting | ✅ | GtkSourceView built-in |
| Code navigation | ✅ | Regex-based import resolution |
| Autocompletion | ✅ | Babel-based symbol parsing |
| Linting / diagnostics | ✅ | `eslint` by default |
| Format on save | ✅ | `prettier` by default |
| Debugger | 🔜 | Planned |

### Terraform (`.tf`)

| Capability | Status | Notes |
|---|---|---|
| Syntax highlighting | ✅ | GtkSourceView + custom HCL spec |
| Code navigation | ✅ | Resource block regex matching |
| Autocompletion | ✅ | Schema-based HCL completion |
| Linting / diagnostics | ✅ | Configurable |
| Format on save | ✅ | Configurable |
| Debugger | 🔜 | Planned |

---

## Customising Linters and Formatters

All linting and formatting is **fully configurable** in `~/.zen_ide/settings.json`. You are not locked into the defaults — any CLI tool that reads from stdin or a file path and writes diagnostics to stdout can be plugged in.

```json
{
  "diagnostics": {
    ".py": {
      "command": "mypy --show-column-numbers {file}",
      "format": "line"
    }
  },
  "formatters": {
    ".py": "black {file}"
  }
}
```

See [Settings Reference](Settings) and [Formatters & Linters](Formatters-and-Linters) for the full configuration schema.

---

## File Previews

Certain file types open with a visual preview alongside (or instead of) the text editor:

| Extension | Preview Type | Description |
|---|---|---|
| `.md`, `.markdown` | **Markdown** | Rendered HTML with code block highlighting |
| `.json`, `.yaml` (OpenAPI) | **OpenAPI/Swagger** | Formatted endpoint list with method badges |
| `.html` | **HTML** | Rendered via WebKit |
| `.png`, `.jpg`, `.gif`, `.bmp`, `.svg`, `.webp`, `.ico` | **Image Viewer** | Visual preview |
| Binary files | **Hex Viewer** | Offset + hex dump + ASCII |
| `.zen_sketch` | **Sketch Pad** | ASCII diagram editor |

---

## Other Languages — Syntax Highlighting Only

GtkSourceView provides out-of-the-box syntax highlighting for 100+ additional languages. These do not yet have navigation, completion, or diagnostics, but the goal is to bring every commonly used language up to full support.

| Category | Languages |
|---|---|
| **Systems** | C, C++, Rust, Go, Assembly |
| **JVM** | Java, Kotlin, Scala, Clojure, Groovy |
| **Scripting** | Ruby, PHP, Perl, Lua, R, Julia |
| **Shell** | Bash, Zsh, Fish, PowerShell |
| **Web** | HTML, CSS, SCSS, Less, SVG |
| **Data** | JSON, YAML, TOML, XML, CSV, INI |
| **Markup** | Markdown, LaTeX, reStructuredText |
| **DevOps** | Dockerfile, Makefile, CMake, Meson |
| **Database** | SQL, GraphQL |
| **Config** | Nginx, Apache, systemd, gitconfig |
| **Other** | Swift, Dart, Elixir, Erlang, Haskell, OCaml, F#, Zig, Nim, V, GLSL, Vala |
