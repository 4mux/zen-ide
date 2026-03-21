"""
Inline completion provider — calls AI for code completions.

Uses the GitHub Copilot API directly via HTTP for fast completions (~1s).
API-only — no CLI fallback.
"""

import hashlib
import os
import threading
import time
from collections import OrderedDict
from typing import Callable, Optional

from gi.repository import GLib

from .context_gatherer import CompletionContext
from .copilot_api import CopilotAPI

# Cooldown after API failure before retrying (seconds)
_API_RETRY_COOLDOWN_S = 30


def _dedupe_suggestions(suggestions: list[str]) -> list[str]:
    """Remove duplicate or near-duplicate suggestions."""
    seen: set[str] = set()
    unique: list[str] = []
    for s in suggestions:
        key = s.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


class CompletionCache:
    """LRU cache for inline completion responses.

    Keyed by a hash of the code context near the cursor so that
    trivial edits far from the cursor reuse the same completion.
    """

    def __init__(self, max_size: int = 50):
        self._cache: OrderedDict[str, list[str]] = OrderedDict()
        self._max_size = max_size

    def get(self, context: CompletionContext) -> list[str] | None:
        key = self._make_key(context)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, context: CompletionContext, completions: list[str]):
        key = self._make_key(context)
        self._cache[key] = completions
        self._cache.move_to_end(key)
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self):
        self._cache.clear()

    def _make_key(self, ctx: CompletionContext) -> str:
        # Use the current line + a few preceding lines as the key.
        # This makes the cache insensitive to typing within the current
        # token while still varying by the code context.
        prefix_lines = ctx.prefix.split("\n")
        # Use last 3 lines of prefix (stable across minor edits)
        stable = "\n".join(prefix_lines[-3:]).rstrip()
        data = f"{stable}\x00{ctx.suffix[:60]}\x00{ctx.language}"
        return hashlib.md5(data.encode()).hexdigest()


class InlineCompletionProvider:
    """Calls AI for inline code completions.

    Uses the Copilot API exclusively (FIM endpoint first, chat fallback).
    No CLI fallback — API-only for speed and quality.
    """

    # Shared across all instances so API status survives tab switches
    _shared_api_available: Optional[bool] = None
    _shared_api_fail_time: float = 0

    def __init__(self):
        self._stop_requested = False
        self._api = CopilotAPI()
        self._cache = CompletionCache()

    @property
    def _api_available(self):
        return InlineCompletionProvider._shared_api_available

    @_api_available.setter
    def _api_available(self, value):
        InlineCompletionProvider._shared_api_available = value

    @property
    def _api_fail_time(self):
        return InlineCompletionProvider._shared_api_fail_time

    @_api_fail_time.setter
    def _api_fail_time(self, value):
        InlineCompletionProvider._shared_api_fail_time = value

    def request_completion(
        self,
        context: CompletionContext,
        on_result: Callable[[str], None],
        on_error: Optional[Callable[[str], None]] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ):
        """Request a completion in a background thread.

        Args:
            context: The code context around the cursor.
            on_result: Called on the main thread with the completion text.
            on_error: Called on the main thread if an error occurs.
            on_chunk: Called on the main thread with each streaming token (optional).
        """
        self.cancel()
        self._stop_requested = False

        thread = threading.Thread(
            target=self._run,
            args=(context, on_result, on_error, on_chunk),
            daemon=True,
        )
        thread.start()

    def request_alternatives(
        self,
        context: CompletionContext,
        on_results: Callable[[list[str]], None],
        on_error: Optional[Callable[[str], None]] = None,
        n: int = 3,
    ):
        """Request multiple alternative completions in a background thread.

        Used for suggestion cycling (Alt+]/Alt+[). Requests n completions
        via the multi-completion API endpoints.

        Args:
            context: The code context around the cursor.
            on_results: Called on the main thread with a list of completions.
            on_error: Called on the main thread if an error occurs.
            n: Number of alternatives to request.
        """
        self.cancel()
        self._stop_requested = False

        thread = threading.Thread(
            target=self._run_multi,
            args=(context, on_results, on_error, n),
            daemon=True,
        )
        thread.start()

    def cancel(self):
        """Cancel any in-flight completion request."""
        self._stop_requested = True

    def _run(
        self,
        context: CompletionContext,
        on_result: Callable[[str], None],
        on_error: Optional[Callable[[str], None]],
        on_chunk: Optional[Callable[[str], None]] = None,
    ):
        """Run the completion request in a background thread."""
        t0 = time.monotonic()

        try:
            # Check cache first
            cached = self._cache.get(context)
            if cached:
                if not self._stop_requested and cached:
                    GLib.idle_add(on_result, cached[0])
                return

            from shared.settings import get_setting

            model = get_setting("ai.inline_completion.model", "gpt-4.1-mini")

            # Retry API after cooldown if previously failed
            api_ok = self._api_available is not False or (time.time() - self._api_fail_time > _API_RETRY_COOLDOWN_S)

            if api_ok and self._api.is_available():
                # FIM endpoint only — no chat fallback to avoid doubling
                # API requests (each request costs premium request units).
                completion = self._try_fim(context, t0)
                if completion:
                    self._cache.put(context, [completion])
                    GLib.idle_add(on_result, completion)
                    return
                if self._stop_requested:
                    return
            else:
                pass

        # Boundary catch: completion backends run external/network code paths.
        except Exception as e:
            if on_error and not self._stop_requested:
                GLib.idle_add(on_error, str(e))

    def _run_multi(
        self,
        context: CompletionContext,
        on_results: Callable[[list[str]], None],
        on_error: Optional[Callable[[str], None]],
        n: int = 3,
    ):
        """Request multiple alternative completions in a background thread."""
        t0 = time.monotonic()

        try:
            # Check cache for multiple completions
            cached = self._cache.get(context)
            if cached and len(cached) > 1:
                if not self._stop_requested:
                    GLib.idle_add(on_results, cached)
                return

            from shared.settings import get_setting

            model = get_setting("ai.inline_completion.model", "gpt-4.1-mini")
            api_ok = self._api_available is not False or (time.time() - self._api_fail_time > _API_RETRY_COOLDOWN_S)

            if not (api_ok and self._api.is_available()):
                return

            # 1. Try FIM multi first
            completions = self._try_fim_multi(context, t0, n)
            if completions:
                self._cache.put(context, completions)
                if not self._stop_requested:
                    GLib.idle_add(on_results, completions)
                return
            if self._stop_requested:
                return

            # 2. Fall back to chat multi
            completions = self._try_chat_multi(context, model, t0, n)
            if completions:
                self._cache.put(context, completions)
                if not self._stop_requested:
                    GLib.idle_add(on_results, completions)
                return

        # Boundary catch: completion backends run external/network code paths.
        except Exception as e:
            if on_error and not self._stop_requested:
                GLib.idle_add(on_error, str(e))

    def _try_fim(self, context: CompletionContext, t0: float) -> str | None:
        """Try the FIM completions endpoint (prefix/suffix)."""

        completion = self._api.complete_fim(
            prefix=context.prefix,
            suffix=context.suffix,
            language=context.language,
            file_path=context.file_path,
            max_tokens=500,
            timeout=10,
        )

        if self._stop_requested:
            return None

        if completion:
            self._api_available = True
            completion = completion.rstrip()
            if self._is_prose_response(completion):
                return None
            completion = self._deduplicate(completion, context)
            completion = self._ensure_newline_boundary(completion, context)
            if completion:
                return completion
        else:
            pass

        return None

    def _try_chat(
        self,
        context: CompletionContext,
        model: str,
        t0: float,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str | None:
        """Try the chat completions endpoint with FIM-style prompt."""
        prompt = self._build_prompt(context)

        if on_chunk:
            completion = self._api.complete_stream(
                prompt,
                model=model,
                max_tokens=500,
                timeout=15,
                on_chunk=on_chunk,
            )
        else:
            completion = self._api.complete(prompt, model=model, max_tokens=500, timeout=15)

        if self._stop_requested:
            return None

        if completion:
            self._api_available = True
            completion = self._clean_response(completion)
            completion = self._deduplicate(completion, context)
            completion = self._ensure_newline_boundary(completion, context)
            if completion:
                return completion
        else:
            self._api_available = False
            self._api_fail_time = time.time()

        return None

    def _try_fim_multi(self, context: CompletionContext, t0: float, n: int) -> list[str]:
        """Try FIM endpoint for multiple completions."""

        raw_completions = self._api.complete_fim_multi(
            prefix=context.prefix,
            suffix=context.suffix,
            language=context.language,
            file_path=context.file_path,
            max_tokens=500,
            timeout=15,
            n=n,
        )

        if self._stop_requested:
            return []

        results: list[str] = []
        for comp in raw_completions:
            comp = comp.rstrip()
            if not comp or self._is_prose_response(comp):
                continue
            comp = self._deduplicate(comp, context)
            comp = self._ensure_newline_boundary(comp, context)
            if comp:
                results.append(comp)

        if results:
            self._api_available = True

        return _dedupe_suggestions(results)

    def _try_chat_multi(self, context: CompletionContext, model: str, t0: float, n: int) -> list[str]:
        """Try chat endpoint for multiple completions."""
        prompt = self._build_prompt(context)

        raw_completions = self._api.complete_multi(prompt, model=model, max_tokens=500, timeout=15, n=n)

        if self._stop_requested:
            return []

        results: list[str] = []
        for comp in raw_completions:
            comp = self._clean_response(comp)
            comp = self._deduplicate(comp, context)
            comp = self._ensure_newline_boundary(comp, context)
            if comp:
                results.append(comp)

        if results:
            self._api_available = True
        else:
            self._api_available = False
            self._api_fail_time = time.time()

        return _dedupe_suggestions(results)

    # FIM cursor marker used in structured prompts
    _FIM_CURSOR = "█"

    def _build_prompt(self, context: CompletionContext) -> str:
        """Build a FIM-style prompt with prefix█suffix format.

        Uses a fill-in-middle structure that models are optimised for,
        instead of a chat-style instruction prompt.  Related file
        snippets (if any) are prepended as comments.
        """
        lang = context.language or "code"
        file_info = f"# File: {os.path.basename(context.file_path)}" if context.file_path else ""

        parts: list[str] = []

        # Cross-file context snippets
        if hasattr(context, "related_snippets") and context.related_snippets:
            parts.append("# Related files:")
            for snip in context.related_snippets:
                label = os.path.basename(snip.file_path)
                parts.append(f"# --- {label} ({snip.relevance}) ---")
                parts.append(snip.content)
            parts.append("")

        if file_info:
            parts.append(file_info)
        parts.append(f"```{lang}")
        parts.append(f"{context.prefix}{self._FIM_CURSOR}{context.suffix}")
        parts.append("```")

        return "\n".join(parts)

    # Phrases that indicate a prose/review response rather than code completion
    _PROSE_INDICATORS = (
        "well-structured",
        "no changes",
        "code review",
        "looks good",
        "is correct",
        "is fine",
        "no issues",
        "no bugs",
        "not needed",
        "already handles",
        "you can ",
        "you may ",
        "you should ",
        "i would ",
        "i suggest",
        "here is ",
        "here's ",
        "the code ",
        "this code ",
        "this function ",
        "this method ",
        "this class ",
        "as follows",
        "for example",
        "note that",
        "in summary",
        "in conclusion",
    )

    def _is_prose_response(self, text: str) -> bool:
        """Detect if the response is prose/commentary rather than code.

        Chat models sometimes return natural language explanations instead of
        code completions. This heuristic catches those responses so they can
        be discarded rather than inserted as ghost text.
        """
        if not text or len(text) < 20:
            return False

        lower = text.lower()

        # Check for known prose phrases
        if any(phrase in lower for phrase in self._PROSE_INDICATORS):
            return True

        # Heuristic: high ratio of spaces to total chars suggests prose
        first_line = text.split("\n")[0]
        if first_line and len(first_line) > 30:
            space_ratio = first_line.count(" ") / len(first_line)
            words = first_line.split()
            avg_word_len = sum(len(w) for w in words) / max(len(words), 1)
            if space_ratio > 0.35 and avg_word_len < 5 and len(words) > 8:
                return True

        return False

    def _clean_response(self, text: str) -> str:
        """Strip markdown fences and trailing whitespace from an API response.

        FIM-style prompts produce cleaner responses, but models may still
        wrap output in markdown fences. Leading whitespace on the first line
        is preserved because the completion is inserted verbatim at the
        cursor position (e.g. ' not ...' after 'if').

        A leading newline is preserved when present — it signals that the
        completion should start on a new line rather than appending to the
        current one (e.g. function body after ``def handler():``).
        """
        # Detect whether the response starts with a newline (possibly after
        # horizontal whitespace).  This signal must survive cleaning so that
        # the insertion places the completion on a new line when appropriate.
        starts_with_newline = text.lstrip(" \t").startswith(("\n", "\r"))

        text = text.strip("\n\r")
        if not text:
            return ""

        # Remove markdown code fences
        if text.lstrip().startswith("```"):
            lines = text.strip().split("\n")
            if len(lines) >= 3 and lines[-1].strip() == "```":
                text = "\n".join(lines[1:-1])
            elif len(lines) >= 2:
                text = "\n".join(lines[1:])

        # Strip the FIM cursor marker if echoed back
        text = text.replace("█", "")

        text = text.strip("`").rstrip()
        if not text:
            return ""

        # Reject prose/commentary responses
        if self._is_prose_response(text):
            return ""

        # Restore leading newline so insertion starts on a new line
        if starts_with_newline and text and not text.startswith("\n"):
            text = "\n" + text

        return text

    def _ensure_newline_boundary(self, completion: str, context: CompletionContext) -> str:
        """Prepend a newline when the completion belongs on a new line.

        FIM models sometimes omit the leading newline when the completion
        represents a new indented block (e.g. function body after ``def foo():``).
        Detects this by checking whether the completion starts with indentation
        while the prefix line already has content.
        """
        if not completion or completion[0] in ("\n", "\r"):
            return completion

        prefix_lines = context.prefix.split("\n")
        last_prefix_line = prefix_lines[-1] if prefix_lines else ""

        if not last_prefix_line.strip():
            return completion

        if completion.startswith("  ") or completion.startswith("\t"):
            return "\n" + completion

        return completion

    def _deduplicate(self, completion: str, context: CompletionContext) -> str:
        """Strip lines from the completion that duplicate existing prefix/suffix code.

        AI models using chat completions (not FIM) sometimes repeat lines that
        already exist before or after the cursor. This detects such overlaps and
        strips them to prevent garbled output after acceptance.
        """
        if not completion:
            return completion

        comp_lines = completion.split("\n")
        prefix_lines = context.prefix.split("\n")

        # Build set of substantial stripped prefix lines (last 20 lines)
        prefix_set: set[str] = set()
        for pl in prefix_lines[-20:]:
            s = pl.strip()
            if len(s) >= 8:
                prefix_set.add(s)

        # Strip leading completion lines that appear verbatim in the prefix
        strip_count = 0
        found_dup = False
        for line in comp_lines:
            s = line.strip()
            if not s:
                strip_count += 1
                continue
            if s in prefix_set:
                strip_count += 1
                found_dup = True
            else:
                break

        # Only strip if we found actual duplicate content lines.
        # Leading empty lines alone are meaningful newline boundaries
        # (e.g. "\n    body_code" after "def handler():").
        if strip_count > 0 and not found_dup:
            strip_count = 0

        if strip_count > 0:
            comp_lines = comp_lines[strip_count:]

        if not comp_lines:
            return ""

        # Strip trailing completion lines that appear verbatim in the suffix
        if context.suffix:
            suffix_lines = context.suffix.split("\n")
            suffix_set: set[str] = set()
            for sl in suffix_lines[:20]:
                s = sl.strip()
                if len(s) >= 8:
                    suffix_set.add(s)

            strip_count = 0
            for line in reversed(comp_lines):
                s = line.strip()
                if not s:
                    strip_count += 1
                    continue
                if s in suffix_set:
                    strip_count += 1
                else:
                    break

            if strip_count > 0:
                comp_lines = comp_lines[:-strip_count]

        if not comp_lines:
            return ""

        # Character-level prefix overlap: strip text from start of completion
        # that the user already typed on the current line.
        # E.g. user typed "respo", AI returns "response = ...", strip "respo"
        # so ghost text becomes "nse = ..." and inserts correctly.
        prefix_lines = context.prefix.split("\n")
        current_line = prefix_lines[-1] if prefix_lines else ""
        if current_line.strip():
            first_comp_line = comp_lines[0]
            max_check = min(len(current_line), len(first_comp_line))
            overlap = 0
            for length in range(max_check, 0, -1):
                if first_comp_line.startswith(current_line[-length:]):
                    overlap = length
                    break
            if overlap > 0:
                comp_lines[0] = first_comp_line[overlap:]
                # If first line became empty and there are more lines, keep it
                # (it represents a newline boundary)
                if not comp_lines[0] and len(comp_lines) == 1:
                    return ""

        return "\n".join(comp_lines)
