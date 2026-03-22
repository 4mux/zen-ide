# Language Examples

The `examples/` folder at the root of the repository contains sample source files for testing how Zen IDE behaves with different programming languages — syntax highlighting, autocomplete, navigation, formatting, and previews.

## Purpose

Use these files to:
- Verify syntax highlighting is correct for a language
- Test autocomplete and code navigation behaviour
- Reproduce or isolate editor issues with a specific language
- Check formatting and diagnostics integration

## Structure

```
examples/
└── cpp/          # C++ sample files
```

Each subdirectory is named after the language or ecosystem it targets and contains representative source files exercising the relevant constructs (classes, templates, imports, closures, etc.).

## Adding a New Language Example

1. Create a subdirectory under `examples/` named after the language (e.g. `examples/rust/`).
2. Add one or more source files that cover typical constructs for that language.
3. Open the files in Zen IDE and verify the expected feature level (see [Supported Languages](Supported-Languages)).

## Feature Levels to Test

| Feature | How to verify |
|---|---|
| Syntax highlighting | Open the file — keywords, strings, and comments should be coloured |
| Semantic highlighting | Edit the file — variables and type annotations should update live |
| Autocomplete | Type inside a scope and trigger completion |
| Code navigation | Cmd+Click a symbol to jump to its definition |
| Format on save | Save the file and check indentation/whitespace is normalised |
| Diagnostics | Introduce a deliberate error and check the gutter indicator |

See [Supported Languages & File Types](Supported-Languages) for the full feature matrix per language.
