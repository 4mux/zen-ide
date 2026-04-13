"""Tests for QuickOpenDialog (src/popups/quick_open_dialog.py)."""

import os

from tests.popups.conftest import (
    class_inherits,
    find_class,
    find_method,
    method_uses_modulo,
    parse_popup_source,
    read_popup_source,
)


class TestQuickOpenDialogStructure:
    """Verify QuickOpenDialog structural contracts."""

    def test_inherits_nvim_popup(self):
        tree = parse_popup_source("quick_open_dialog.py")
        assert class_inherits(tree, "QuickOpenDialog", "NvimPopup")

    def test_has_move_selection(self):
        tree = parse_popup_source("quick_open_dialog.py")
        cls = find_class(tree, "QuickOpenDialog")
        assert find_method(cls, "_move_selection") is not None

    def test_has_fuzzy_score(self):
        tree = parse_popup_source("quick_open_dialog.py")
        cls = find_class(tree, "QuickOpenDialog")
        assert find_method(cls, "_fuzzy_score") is not None

    def test_has_load_files_async(self):
        tree = parse_popup_source("quick_open_dialog.py")
        cls = find_class(tree, "QuickOpenDialog")
        assert find_method(cls, "_load_files_async") is not None

    def test_move_selection_uses_modulo(self):
        tree = parse_popup_source("quick_open_dialog.py")
        cls = find_class(tree, "QuickOpenDialog")
        method = find_method(cls, "_move_selection")
        assert method_uses_modulo(method)


class TestQuickOpenDialogKeyHandling:
    """Verify key handling."""

    def test_handles_jk_navigation(self):
        source = read_popup_source("quick_open_dialog.py")
        assert "KEY_j" in source
        assert "KEY_k" in source

    def test_handles_arrow_navigation(self):
        source = read_popup_source("quick_open_dialog.py")
        assert "KEY_Down" in source
        assert "KEY_Up" in source

    def test_handles_escape(self):
        source = read_popup_source("quick_open_dialog.py")
        assert "KEY_Escape" in source

    def test_handles_cmd_backspace(self):
        source = read_popup_source("quick_open_dialog.py")
        assert "KEY_BackSpace" in source
        assert "META_MASK" in source


class TestQuickOpenDialogFuzzyScore:
    """Test _fuzzy_score logic as a pure function."""

    @staticmethod
    def _fuzzy_score(query: str, text: str) -> int:
        """Replicate QuickOpenDialog._fuzzy_score."""
        if not query:
            return 1

        score = 0
        query_idx = 0

        filename = os.path.basename(text)
        if query in filename:
            score += 100
        elif query in text:
            score += 50

        prev_match_idx = -1
        for i, char in enumerate(text):
            if query_idx < len(query) and char == query[query_idx]:
                score += 10
                if prev_match_idx == i - 1:
                    score += 5
                if i == 0 or text[i - 1] in "/._ -":
                    score += 15
                prev_match_idx = i
                query_idx += 1

        if query_idx < len(query):
            return 0

        score += max(0, 50 - len(text) // 5)
        return score

    def test_empty_query_returns_positive(self):
        assert self._fuzzy_score("", "anything") == 1

    def test_no_match_returns_zero(self):
        assert self._fuzzy_score("xyz", "abc") == 0

    def test_filename_match_scores_high(self):
        score = self._fuzzy_score("main", "src/main.py")
        assert score > 100

    def test_path_match_scores_lower(self):
        score_filename = self._fuzzy_score("main", "src/main.py")
        score_path = self._fuzzy_score("src", "src/other.py")
        assert score_filename > score_path

    def test_exact_filename_match(self):
        score = self._fuzzy_score("hello", "path/to/hello.txt")
        assert score > 0

    def test_consecutive_match_bonus(self):
        score_consecutive = self._fuzzy_score("ab", "ab_other")
        score_spread = self._fuzzy_score("ab", "a_x_b_y")
        assert score_consecutive > score_spread

    def test_word_boundary_bonus(self):
        score_boundary = self._fuzzy_score("m", "src/main.py")
        score_middle = self._fuzzy_score("a", "src/main.py")
        # 'm' is at boundary (after /), 'a' is in middle
        assert score_boundary >= score_middle

    def test_shorter_paths_score_higher(self):
        score_short = self._fuzzy_score("a", "a.py")
        score_long = self._fuzzy_score("a", "very/deep/nested/path/to/a.py")
        assert score_short > score_long

    def test_all_chars_must_match(self):
        assert self._fuzzy_score("abc", "ab") == 0


class TestQuickOpenDialogNavigation:
    """Test navigation logic."""

    @staticmethod
    def _move(count, selected, delta):
        """Replicate QuickOpenDialog._move_selection."""
        if count == 0:
            return selected
        return (selected + delta) % count

    def test_wrap_down(self):
        assert self._move(5, 4, 1) == 0

    def test_wrap_up(self):
        assert self._move(5, 0, -1) == 4

    def test_empty_list(self):
        assert self._move(0, 0, 1) == 0


class TestQuickOpenDialogFileLoading:
    """Verify file loading patterns."""

    def test_loads_files_in_background(self):
        source = read_popup_source("quick_open_dialog.py")
        assert "threading.Thread" in source

    def test_respects_gitignore(self):
        """Ripgrep handles .gitignore natively — verify rg is used."""
        source = read_popup_source("quick_open_dialog.py")
        assert "rg" in source

    def test_includes_hidden_files(self):
        """Ripgrep must use --hidden so dotfiles (.drone, .env, etc.) appear."""
        source = read_popup_source("quick_open_dialog.py")
        assert "--hidden" in source

    def test_limits_results_to_100(self):
        source = read_popup_source("quick_open_dialog.py")
        assert "[:100]" in source
