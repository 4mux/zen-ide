# AI Inline Code Completion

**Created_at:** 2026-03-04
**Updated_at:** 2026-03-21
**Status:** Partially superseded
**Goal:** Implement inline ghost text AI code completions with streaming and multi-line support
**Scope:** `src/editor/inline_completion/`

> **Note (2026-03-21):** The inline completion system is still active and uses the Copilot HTTP API (`src/editor/inline_completion/copilot_api.py`). However, references to CLI-based providers (`src/ai/claude_cli_provider.py`, `src/ai/copilot_cli_provider.py`, `src/ai/pty_cli_provider.py`) in this doc are outdated — those files have been deleted. The AI chat system now uses a VTE terminal running CLIs directly; see [2026_03_21_ai_terminal.md](2026_03_21_ai_terminal.md).  

---

## Overview

Zen IDE provides **inline ghost text suggestions** — AI-powered code completions that appear as dimmed text at the cursor position. The system uses the fastest available AI model via Copilot CLI or Claude CLI to generate context-aware completions that users can accept with Tab.

## Goals

- **Ghost text rendering**: Show AI suggestions as dimmed inline text at cursor position
- **Multi-line completions**: Support multi-line suggestions (e.g., entire function bodies)
- **Streaming completions**: Show suggestions as they arrive from AI
- **Partial accept**: Accept word-by-word or line-by-line (Cmd+Right / Cmd+Down)
- **Context-aware**: Use surrounding code, file path, language, and project context
- **Multiple suggestions**: Cycle through alternative completions (Alt+] / Alt+[)
- **Non-blocking**: Async completions that don't freeze the editor

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Zen IDE Editor                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │                    InlineCompletionManager                      │    │
│   │  - Coordinates trigger, context, rendering, and accept flow     │    │
│   │  - Debounces keystrokes (configurable delay ~500-800ms)         │    │
│   │  - Manages completion lifecycle (request → display → accept)    │    │
│   └──────────────────────────┬─────────────────────────────────────┘    │
│                              │                                           │
│          ┌───────────────────┼───────────────────┐                       │
│          ▼                   ▼                   ▼                       │
│   ┌─────────────┐    ┌─────────────────┐   ┌─────────────────┐          │
│   │  Context    │    │   AI Provider   │   │  Ghost Text     │          │
│   │  Gatherer   │    │   Interface     │   │  Renderer       │          │
│   │             │    │                 │   │                 │          │
│   │ • prefix    │    │ • Copilot CLI   │   │ • GtkSourceView │          │
│   │ • suffix    │    │ • Claude CLI    │   │   text tags     │          │
│   │ • file path │    │ • streaming     │   │ • dimmed style  │          │
│   │ • language  │    │ • cancellation  │   │ • cursor sync   │          │
│   │ • imports   │    │                 │   │                 │          │
│   └─────────────┘    └─────────────────┘   └─────────────────┘          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Current State Analysis

### What Exists

| Component | Location | Status |
|-----------|----------|--------|
| Popup autocomplete | `src/editor/autocomplete/` | ✅ Working (Ctrl+Space) |
| AI providers | `src/ai/` | ✅ Claude CLI, Copilot CLI |
| PTY streaming | `src/ai/pty_cli_provider.py` | ✅ Real-time streaming |
| Setting flag | `ai.show_inline_suggestions` | ✅ Exists (default: True) |
| Context callbacks | `src/ai/ai_chat_terminal.py` | ✅ File content, cursor pos |
| Ghost text renderer | `src/editor/inline_completion/ghost_text_renderer.py` | ✅ Working |
| Inline completion manager | `src/editor/inline_completion/inline_completion_manager.py` | ✅ Working |
| Context gatherer | `src/editor/inline_completion/context_gatherer.py` | ✅ Working |
| Completion provider | `src/editor/inline_completion/inline_completion_provider.py` | ✅ Working |

### Future Enhancements

| Feature | Description |
|---------|-------------|
| Streaming display | Update ghost text as tokens arrive (currently waits for full response) |
| Suggestion cycling | Navigate between multiple alternative suggestions (Alt+] / Alt+[) |

## Implementation Plan

### Phase 1: Ghost Text Renderer

**Goal**: Render ghost text in GtkSourceView using text tags

**Files to create**:
- `src/editor/inline_completion/ghost_text_renderer.py`

**Implementation**:
```python
class GhostTextRenderer:
    """Renders AI suggestions as dimmed ghost text in the editor."""
    
    def __init__(self, source_view: GtkSource.View):
        self._view = source_view
        self._buffer = source_view.get_buffer()
        self._ghost_tag = self._create_ghost_tag()
        self._ghost_mark = None  # GtkTextMark at insertion point
        self._ghost_text = ""
        
    def _create_ghost_tag(self) -> Gtk.TextTag:
        """Create a text tag for ghost text styling."""
        tag = self._buffer.create_tag(
            "ghost-text",
            foreground_rgba=Gdk.RGBA(0.5, 0.5, 0.5, 0.6),  # Dimmed
            style=Pango.Style.ITALIC,
        )
        return tag
        
    def show(self, text: str, at_iter: Gtk.TextIter):
        """Show ghost text at the given position."""
        self.clear()
        self._ghost_text = text
        self._ghost_mark = self._buffer.create_mark("ghost", at_iter, True)
        # Insert ghost text with tag
        self._buffer.insert_with_tags(at_iter, text, self._ghost_tag)
        
    def clear(self):
        """Remove ghost text from display."""
        if self._ghost_mark:
            # Remove the ghost text range
            start = self._buffer.get_iter_at_mark(self._ghost_mark)
            end = start.copy()
            end.forward_chars(len(self._ghost_text))
            self._buffer.delete(start, end)
            self._buffer.delete_mark(self._ghost_mark)
            self._ghost_mark = None
            self._ghost_text = ""
            
    def accept(self) -> str:
        """Accept ghost text (converts to real text)."""
        text = self._ghost_text
        self.clear()
        return text
        
    def accept_word(self) -> str:
        """Accept first word of ghost text."""
        # Split at word boundary and accept first word
        ...
        
    def accept_line(self) -> str:
        """Accept first line of ghost text."""
        # Accept up to first newline
        ...
```

**Key challenges**:
- GTK TextBuffer doesn't have true "virtual" text - ghost text is inserted as real characters
- Need to track and remove ghost text when user types or moves cursor
- Multi-line ghost text positioning needs care

**Alternative approach**: Use GtkSourceView's `GtkSourceGutterRenderer` or custom drawing via `draw` signal for true overlay rendering (more complex but cleaner).

---

### Phase 2: Context Gatherer

**Goal**: Build rich context for AI completion requests (FIM format)

**Files to create**:
- `src/editor/inline_completion/context_gatherer.py`

**Context structure**:
```python
@dataclass
class CompletionContext:
    prefix: str          # Code before cursor (last ~2000 chars)
    suffix: str          # Code after cursor (next ~500 chars)
    file_path: str       # Full path for language detection
    language: str        # "python", "javascript", etc.
    cursor_line: int     # Current line number
    cursor_col: int      # Current column
    imports: list[str]   # Parsed imports for better context
    repo_root: str       # Project root for relative paths
```

**Gathering logic**:
```python
class ContextGatherer:
    def gather(self, editor_tab) -> CompletionContext:
        buffer = editor_tab.buffer
        cursor = buffer.get_iter_at_mark(buffer.get_insert())
        
        # Get prefix (all text before cursor, limited)
        start = buffer.get_start_iter()
        prefix = buffer.get_text(start, cursor, False)[-2000:]
        
        # Get suffix (text after cursor, limited)
        end = buffer.get_end_iter()
        suffix = buffer.get_text(cursor, end, False)[:500]
        
        # Detect language from file extension
        language = detect_language(editor_tab.file_path)
        
        return CompletionContext(
            prefix=prefix,
            suffix=suffix,
            file_path=editor_tab.file_path,
            language=language,
            cursor_line=cursor.get_line() + 1,
            cursor_col=cursor.get_line_offset(),
            imports=parse_imports(prefix, language),
            repo_root=find_repo_root(editor_tab.file_path),
        )
```

---

### Phase 3: AI Provider Interface

**Goal**: Abstract interface for AI completion providers

**Files to create**:
- `src/editor/inline_completion/completion_provider.py`

**Interface**:
```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

class InlineCompletionProvider(ABC):
    """Base class for AI inline completion providers."""
    
    @abstractmethod
    async def get_completions(
        self, 
        context: CompletionContext,
        max_suggestions: int = 3
    ) -> AsyncIterator[str]:
        """Yield completion text tokens as they arrive."""
        pass
        
    @abstractmethod
    def cancel(self):
        """Cancel any in-flight completion request."""
        pass
```

**Copilot CLI provider**:
```python
class CopilotInlineProvider(InlineCompletionProvider):
    """Uses GitHub Copilot CLI for completions."""
    
    async def get_completions(self, context: CompletionContext, max_suggestions: int = 3):
        # Build prompt with FIM markers
        prompt = f"""<|fim_prefix|>{context.prefix}<|fim_suffix|>{context.suffix}<|fim_middle|>"""
        
        # Call gh copilot with streaming
        process = await asyncio.create_subprocess_exec(
            "gh", "copilot", "suggest", "--shell", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        async for line in process.stdout:
            yield line.decode()
```

**Claude CLI provider**:
```python
class ClaudeInlineProvider(InlineCompletionProvider):
    """Uses Claude CLI for completions."""
    
    async def get_completions(self, context: CompletionContext, max_suggestions: int = 3):
        # Build system prompt for code completion
        system = f"""You are a code completion assistant. Complete the code at the cursor position.
Language: {context.language}
File: {context.file_path}

Return ONLY the completion text, no explanations."""
        
        prompt = f"""Complete this code:
```{context.language}
{context.prefix}█{context.suffix}
```
The █ marks where the cursor is. Return only the code that should go there."""
        
        # Use existing PTY provider for streaming
        async for token in self._pty_provider.stream(prompt, system):
            yield token
```

---

### Phase 4: Inline Completion Manager

**Goal**: Coordinate the entire inline completion flow

**Files to create**:
- `src/editor/inline_completion/inline_completion_manager.py`

**Implementation**:
```python
class InlineCompletionManager:
    """Manages AI inline completions for an editor tab."""
    
    def __init__(self, editor_tab):
        self._tab = editor_tab
        self._renderer = GhostTextRenderer(editor_tab.view)
        self._gatherer = ContextGatherer()
        self._provider = self._get_provider()  # Based on settings
        self._trigger_timer = None
        self._current_request = None
        self._suggestions = []  # List of alternative completions
        self._suggestion_idx = 0
        
        # Connect to editor events
        self._tab.buffer.connect("changed", self._on_buffer_changed)
        self._tab.buffer.connect("cursor-moved", self._on_cursor_moved)
        
    def _on_buffer_changed(self, buffer):
        """Handle text changes - trigger completion after delay."""
        # Cancel any pending request
        self._cancel_pending()
        self._renderer.clear()
        
        # Don't trigger during programmatic changes
        if self._tab._inserting:
            return
            
        # Start debounce timer
        delay = get_setting("ai.inline_completion_delay", 800)
        self._trigger_timer = GLib.timeout_add(delay, self._trigger_completion)
        
    def _trigger_completion(self):
        """Request AI completion after debounce."""
        self._trigger_timer = None
        
        # Gather context
        context = self._gatherer.gather(self._tab)
        
        # Skip if line is empty or just whitespace
        if not context.prefix.strip():
            return False
            
        # Request completion asynchronously
        self._current_request = asyncio.create_task(self._fetch_completion(context))
        return False  # Don't repeat timer
        
    async def _fetch_completion(self, context: CompletionContext):
        """Fetch completion from AI provider."""
        try:
            completion = ""
            async for token in self._provider.get_completions(context):
                completion += token
                # Update ghost text incrementally (streaming)
                GLib.idle_add(self._update_ghost_text, completion)
                
            self._suggestions = [completion]  # TODO: multiple suggestions
            
        except asyncio.CancelledError:
            pass
            
    def _update_ghost_text(self, text: str):
        """Update ghost text display (called from main thread)."""
        cursor = self._tab.buffer.get_iter_at_mark(self._tab.buffer.get_insert())
        self._renderer.show(text, cursor)
        return False  # GLib.idle_add callback
        
    def accept(self):
        """Accept the current suggestion (Tab key)."""
        text = self._renderer.accept()
        if text:
            self._tab.buffer.insert_at_cursor(text)
            self._suggestions = []
            
    def accept_word(self):
        """Accept next word of suggestion (Cmd+Right)."""
        text = self._renderer.accept_word()
        if text:
            self._tab.buffer.insert_at_cursor(text)
            
    def accept_line(self):
        """Accept next line of suggestion (Cmd+Down)."""
        text = self._renderer.accept_line()
        if text:
            self._tab.buffer.insert_at_cursor(text)
            
    def next_suggestion(self):
        """Cycle to next suggestion (Alt+])."""
        if len(self._suggestions) > 1:
            self._suggestion_idx = (self._suggestion_idx + 1) % len(self._suggestions)
            self._show_current_suggestion()
            
    def prev_suggestion(self):
        """Cycle to previous suggestion (Alt+[)."""
        if len(self._suggestions) > 1:
            self._suggestion_idx = (self._suggestion_idx - 1) % len(self._suggestions)
            self._show_current_suggestion()
            
    def dismiss(self):
        """Dismiss current suggestion (Escape)."""
        self._cancel_pending()
        self._renderer.clear()
        self._suggestions = []
```

---

### Phase 5: Keybindings Integration

**Goal**: Add keyboard shortcuts for inline completions

**File to modify**: `src/keybindings.py`

**New bindings**:
```python
# Inline AI Completions
("Tab", None, "editor", "inline_completion_accept", "Accept AI suggestion"),
("Escape", None, "editor", "inline_completion_dismiss", "Dismiss AI suggestion"),
("Right", "Primary", "editor", "inline_completion_accept_word", "Accept next word"),
("Down", "Primary", "editor", "inline_completion_accept_line", "Accept next line"),
("bracketright", "Alt", "editor", "inline_completion_next", "Next suggestion"),
("bracketleft", "Alt", "editor", "inline_completion_prev", "Previous suggestion"),
```

**Conflict handling**:
- Tab already used for indentation → only accept if ghost text is visible
- Escape already used to dismiss autocomplete popup → ghost text takes priority

---

### Phase 6: Settings & Configuration

**File to modify**: `src/shared/settings/default_settings.py`

**New settings**:
```python
"ai": {
    ...
    "inline_completion": {
        "enabled": True,                    # Master toggle
        "trigger_delay_ms": 800,            # Debounce delay
        "max_suggestions": 3,               # Number of alternatives
        "max_completion_tokens": 500,       # Max tokens per completion
        "show_in_comments": False,          # Suggest in comments?
        "show_in_strings": False,           # Suggest in strings?
        "languages": {                      # Per-language toggle
            "python": True,
            "javascript": True,
            "typescript": True,
            "go": True,
            "rust": True,
        },
    },
},
```

---

### Phase 7: Visual Polish

**Goal**: Match industry-standard visual appearance

**Implementation details**:
- Ghost text color: Theme's comment color at 60% opacity
- Italic styling for differentiation
- Status bar indicator: "Copilot ✓" when suggestions available
- Loading indicator: Subtle spinner while fetching

**CSS for ghost text**:
```css
.ghost-text {
    color: alpha(@comment_color, 0.6);
    font-style: italic;
}

.ghost-text-loading {
    /* Subtle pulsing animation */
    animation: ghost-pulse 1.5s ease-in-out infinite;
}
```

---

## File Structure

```
src/editor/inline_completion/
├── __init__.py
├── inline_completion_manager.py   # Main coordinator
├── ghost_text_renderer.py         # GTK rendering
├── context_gatherer.py            # Build AI context
├── completion_provider.py         # Base provider interface
├── copilot_provider.py            # Copilot CLI implementation
└── claude_provider.py             # Claude CLI implementation
```

---

## Testing Strategy

### Unit Tests
- `test_context_gatherer.py` - Context extraction
- `test_ghost_text_renderer.py` - Text tag management
- `test_completion_provider.py` - Provider interface mocking

### Integration Tests
- `test_inline_completion_flow.py` - Full trigger → display → accept flow
- `test_inline_completion_keybindings.py` - Keyboard interaction

### Manual Testing
- Type in Python file, wait for suggestion
- Tab to accept, Escape to dismiss
- Cmd+Right for word-by-word accept
- Alt+] to cycle suggestions
- Verify performance (no UI freezing)

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| GTK text tags don't support "virtual" text | High | Use mark-based insertion with immediate cleanup on keystroke |
| AI latency causes stale suggestions | Medium | Cancel in-flight requests on any keystroke |
| Multi-line ghost text positioning | Medium | Use fixed-width font metrics for positioning |
| Conflict with existing autocomplete | Low | Ghost text dismisses when popup opens |
| CLI tool not installed | Medium | Graceful fallback with "Install Copilot" hint |

---

## Timeline Estimate

| Phase | Effort | Dependencies |
|-------|--------|--------------|
| Phase 1: Ghost Text Renderer | 2-3 days | None |
| Phase 2: Context Gatherer | 1 day | None |
| Phase 3: AI Provider Interface | 2 days | Phase 2 |
| Phase 4: Inline Manager | 3-4 days | Phase 1, 2, 3 |
| Phase 5: Keybindings | 0.5 day | Phase 4 |
| Phase 6: Settings | 0.5 day | Phase 4 |
| Phase 7: Visual Polish | 1-2 days | Phase 4 |

**Total: ~10-12 days**

---

## References

- [GtkSourceView API](https://docs.gtk.org/gtksourceview5/)
- Current Zen autocomplete: `src/editor/autocomplete/autocomplete.py`
- Current AI providers: `src/ai/claude_cli_provider.py`, `src/ai/copilot_cli_provider.py`
