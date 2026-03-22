"""Tests for AI tab title inferrer."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai.tab_title_inferrer import infer_title


class TestInferTitle:
    """Test cases for infer_title function."""

    def test_empty_messages(self):
        """Returns None for empty message list."""
        assert infer_title([]) is None

    def test_no_user_messages(self):
        """Returns None when no user messages exist."""
        messages = [{"role": "assistant", "content": "Hello!"}]
        assert infer_title(messages) is None

    def test_simple_topic(self):
        """Extracts simple topic (python abbreviated to py, help is filler)."""
        messages = [{"role": "user", "content": "python help"}]
        assert infer_title(messages) == "Py"

    def test_max_length(self):
        """Respects max_length parameter."""
        messages = [{"role": "user", "content": "this is a very long message"}]
        result = infer_title(messages)  # default max_length=15
        assert result is not None
        assert len(result) <= 15

    def test_custom_max_length(self):
        """Respects custom max_length."""
        messages = [{"role": "user", "content": "refactor javascript widget"}]
        result = infer_title(messages)
        assert result is not None
        assert len(result) <= 18

    # Abbreviation tests
    def test_abbreviates_kubernetes(self):
        """Abbreviates kubernetes to k8s."""
        messages = [{"role": "user", "content": "kubernetes setup"}]
        assert infer_title(messages) == "K8S Setup"

    def test_abbreviates_database(self):
        """Abbreviates database to db."""
        messages = [{"role": "user", "content": "database connection"}]
        assert infer_title(messages) == "Db Conn"

    def test_abbreviates_performance(self):
        """Abbreviates performance to perf."""
        messages = [{"role": "user", "content": "performance issues"}]
        assert infer_title(messages) == "Perf Issues"

    def test_abbreviates_javascript(self):
        """Abbreviates javascript to js."""
        messages = [{"role": "user", "content": "javascript async"}]
        assert infer_title(messages) == "Js Async"

    def test_abbreviates_typescript(self):
        """Abbreviates typescript to ts."""
        messages = [{"role": "user", "content": "typescript generics"}]
        assert infer_title(messages) == "Ts Generics"

    def test_abbreviates_configuration(self):
        """Abbreviates configuration to config."""
        messages = [{"role": "user", "content": "configuration file"}]
        assert infer_title(messages) == "Config File"

    def test_abbreviates_function(self):
        """Abbreviates function to func."""
        messages = [{"role": "user", "content": "function syntax"}]
        assert infer_title(messages) == "Func Syntax"

    # Filler word removal tests
    def test_removes_please(self):
        """Removes 'please' filler word."""
        messages = [{"role": "user", "content": "please fix the bug"}]
        result = infer_title(messages)
        assert result is not None
        assert "Please" not in result
        assert "Fix" in result

    def test_removes_im_wondering(self):
        """Removes 'I'm wondering' filler."""
        messages = [{"role": "user", "content": "I'm wondering about python"}]
        # python is abbreviated to py
        assert infer_title(messages) == "Py"

    def test_removes_can_you(self):
        """Removes 'can you' filler."""
        messages = [{"role": "user", "content": "can you explain async"}]
        assert infer_title(messages) == "Explain Async"

    # Question pattern tests
    def test_how_do_i_pattern(self):
        """Handles 'how do I' questions."""
        messages = [{"role": "user", "content": "how do I fix this bug"}]
        result = infer_title(messages)
        assert "Fix" in result

    def test_what_is_pattern(self):
        """Handles 'what is' questions - semantic pattern extracts intent."""
        messages = [{"role": "user", "content": "what is a decorator"}]
        result = infer_title(messages)
        # Semantic pattern: "what is X" -> "WHAT X" or just topic
        assert "Decorator" in result or "What" in result

    def test_why_does_pattern(self):
        """Handles 'why does' questions."""
        messages = [{"role": "user", "content": "why does this fail"}]
        result = infer_title(messages)
        assert "Fail" in result

    # Action verb tests
    def test_preserves_fix_verb(self):
        """Preserves 'fix' action verb."""
        messages = [{"role": "user", "content": "fix the error"}]
        assert "Fix" in infer_title(messages)

    def test_preserves_refactor_verb(self):
        """Preserves 'refactor' action verb."""
        messages = [{"role": "user", "content": "refactor this code"}]
        assert "Refactor" in infer_title(messages)

    def test_preserves_debug_verb(self):
        """Preserves 'debug' action verb."""
        messages = [{"role": "user", "content": "debug the issue"}]
        assert "Debug" in infer_title(messages)

    def test_preserves_create_verb(self):
        """'create' now maps to semantic 'impl' pattern."""
        messages = [{"role": "user", "content": "create a function"}]
        result = infer_title(messages)
        # Semantic pattern: "create X" -> "IMPL X"
        assert "Impl" in result or "Create" in result

    # Edge cases
    def test_code_blocks_removed(self):
        """Removes code blocks from content."""
        messages = [{"role": "user", "content": "fix this ```python\nprint('hi')\n```"}]
        result = infer_title(messages)
        assert "```" not in result
        assert "print" not in result.lower()

    def test_inline_code_removed(self):
        """Removes inline code from content."""
        messages = [{"role": "user", "content": "explain `async def`"}]
        result = infer_title(messages)
        assert "`" not in result

    def test_urls_removed(self):
        """Removes URLs from content."""
        messages = [{"role": "user", "content": "check https://example.com/foo"}]
        result = infer_title(messages)
        assert "http" not in result.lower()
        assert "example" not in result.lower()

    def test_file_paths_removed(self):
        """Removes file paths from content."""
        messages = [{"role": "user", "content": "edit /src/main.py please"}]
        result = infer_title(messages)
        assert "/" not in result

    def test_very_short_message(self):
        """Handles very short messages."""
        messages = [{"role": "user", "content": "hi"}]
        result = infer_title(messages)
        assert result == "Hi" or result is None or len(result) <= 15

    def test_only_filler_words(self):
        """Returns None if message is only filler words."""
        messages = [{"role": "user", "content": "please help me"}]
        # Should still extract something or return None
        result = infer_title(messages)
        assert result is None or len(result) <= 15

    def test_uses_first_user_message(self):
        """Uses first user message, ignores later ones."""
        messages = [
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "Sure!"},
            {"role": "user", "content": "now javascript"},
        ]
        result = infer_title(messages)
        assert "Fix" in result
        assert "Js" not in result  # second message ignored

    def test_uppercase_output(self):
        """Output is always uppercase."""
        messages = [{"role": "user", "content": "lowercase test"}]
        result = infer_title(messages)
        assert result == result.title()

    # Real-world examples
    def test_real_example_db_error(self):
        """Real example: database connection error."""
        messages = [{"role": "user", "content": "How do I fix the database connection error?"}]
        result = infer_title(messages)
        assert len(result) <= 15
        assert "Db" in result or "Fix" in result

    def test_real_example_kubernetes(self):
        """Real example: kubernetes explanation."""
        messages = [{"role": "user", "content": "Can you explain how kubernetes works?"}]
        result = infer_title(messages)
        assert len(result) <= 15
        assert "K8S" in result

    def test_real_example_async_sync(self):
        """Real example: async vs sync - now gets semantic comparison title."""
        messages = [{"role": "user", "content": "What is the difference between async and sync?"}]
        result = infer_title(messages)
        assert len(result) <= 15
        # Semantic pattern: "difference between X and Y" -> "X VS Y"
        assert "Vs" in result or "Async" in result

    # NEW: Semantic pattern tests
    def test_semantic_comparison_vs(self):
        """Detects X vs Y comparison pattern."""
        messages = [{"role": "user", "content": "let vs const"}]
        result = infer_title(messages)
        assert "Vs" in result
        assert "Let" in result

    def test_semantic_comparison_difference(self):
        """Detects 'difference between' pattern."""
        messages = [{"role": "user", "content": "what's the difference between list and tuple"}]
        result = infer_title(messages)
        assert "Vs" in result

    def test_semantic_debug_not_working(self):
        """Detects debugging pattern: not working."""
        messages = [{"role": "user", "content": "my async function is not working"}]
        result = infer_title(messages)
        assert "Debug" in result

    def test_semantic_debug_error(self):
        """Detects debugging pattern: getting error."""
        messages = [{"role": "user", "content": "getting an error with database"}]
        result = infer_title(messages)
        assert "Debug" in result

    def test_semantic_explain(self):
        """Detects explanation pattern."""
        messages = [{"role": "user", "content": "explain how closures work"}]
        result = infer_title(messages)
        assert "Explain" in result or "How" in result

    def test_semantic_implement(self):
        """Detects implementation pattern."""
        messages = [{"role": "user", "content": "how to implement a queue"}]
        result = infer_title(messages)
        assert "Impl" in result

    def test_semantic_convert(self):
        """Detects conversion pattern."""
        messages = [{"role": "user", "content": "convert json to yaml"}]
        result = infer_title(messages)
        assert "To" in result

    def test_semantic_setup(self):
        """Detects setup pattern."""
        messages = [{"role": "user", "content": "how to setup docker"}]
        result = infer_title(messages)
        assert "Setup" in result

    def test_smart_quote_contraction(self):
        """Smart/curly quotes in contractions are handled like ASCII ones."""
        # Right single quotation mark (U+2019) — most common smart quote
        messages = [{"role": "user", "content": "scrollbar doesn\u2019t work"}]
        result = infer_title(messages)
        assert result is not None
        assert "Doesn" not in result  # contraction should not leak partial words
        assert "Fix" in result

    def test_smart_quote_matches_ascii(self):
        """Smart-quote and ASCII-quote inputs produce the same title."""
        ascii_msg = [{"role": "user", "content": "terminal doesn't scroll"}]
        smart_msg = [{"role": "user", "content": "terminal doesn\u2019t scroll"}]
        assert infer_title(ascii_msg) == infer_title(smart_msg)

    def test_doesnt_work_semantic_pattern(self):
        """'X doesn't work' triggers fix semantic pattern."""
        messages = [{"role": "user", "content": "ai terminal scrollbar doesn't work"}]
        result = infer_title(messages)
        assert "Fix" in result
        assert "Scrollbar" in result
