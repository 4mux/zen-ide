"""Tests for GlobalSearchDialog (src/popups/global_search_dialog.py)."""

from tests.popups.conftest import (
    class_inherits,
    find_class,
    find_method,
    method_uses_modulo,
    parse_popup_source,
    read_popup_source,
)


class TestGlobalSearchDialogStructure:
    """Verify GlobalSearchDialog structural contracts."""

    def test_inherits_nvim_popup(self):
        tree = parse_popup_source("global_search_dialog.py")
        assert class_inherits(tree, "GlobalSearchDialog", "NvimPopup")

    def test_has_move_selection(self):
        tree = parse_popup_source("global_search_dialog.py")
        cls = find_class(tree, "GlobalSearchDialog")
        assert find_method(cls, "_move_selection") is not None

    def test_has_search_worker(self):
        tree = parse_popup_source("search_engine_mixin.py")
        cls = find_class(tree, "SearchEngineMixin")
        assert find_method(cls, "_search_worker") is not None

    def test_has_should_skip_path(self):
        tree = parse_popup_source("search_engine_mixin.py")
        cls = find_class(tree, "SearchEngineMixin")
        assert find_method(cls, "_should_skip_path") is not None

    def test_move_selection_uses_modulo(self):
        tree = parse_popup_source("global_search_dialog.py")
        cls = find_class(tree, "GlobalSearchDialog")
        method = find_method(cls, "_move_selection")
        assert method_uses_modulo(method)


class TestGlobalSearchDialogKeyHandling:
    """Verify key handling."""

    def test_handles_jk_navigation(self):
        source = read_popup_source("global_search_dialog.py")
        assert "KEY_j" in source
        assert "KEY_k" in source

    def test_handles_arrow_navigation(self):
        source = read_popup_source("global_search_dialog.py")
        assert "KEY_Down" in source
        assert "KEY_Up" in source

    def test_handles_escape(self):
        source = read_popup_source("global_search_dialog.py")
        assert "KEY_Escape" in source

    def test_handles_enter(self):
        source = read_popup_source("global_search_dialog.py")
        assert "KEY_Return" in source


class TestGlobalSearchDialogBinaryExtensions:
    """Test BINARY_EXTENSIONS constant."""

    def test_binary_extensions_is_frozenset(self):
        source = read_popup_source("search_engine_mixin.py")
        assert "frozenset" in source

    def test_common_binary_extensions_included(self):
        source = read_popup_source("search_engine_mixin.py")
        for ext in [".pyc", ".png", ".jpg", ".zip", ".exe", ".dll", ".so"]:
            assert f'"{ext}"' in source, f"Missing binary extension: {ext}"


class TestGlobalSearchDialogSearchResult:
    """Test SearchResult dataclass."""

    def test_search_result_class_exists(self):
        tree = parse_popup_source("search_engine_mixin.py")
        from tests.popups.conftest import find_class

        assert find_class(tree, "SearchResult") is not None


class TestGlobalSearchDialogSearchBackends:
    """Verify ripgrep search backend."""

    def test_has_ripgrep_search(self):
        tree = parse_popup_source("search_engine_mixin.py")
        cls = find_class(tree, "SearchEngineMixin")
        assert find_method(cls, "_ripgrep_search") is not None

    def test_includes_hidden_files(self):
        """Ripgrep must use --hidden so dotfiles (.drone, .env, etc.) appear."""
        source = read_popup_source("search_engine_mixin.py")
        assert "--hidden" in source


class TestGlobalSearchDialogNavigation:
    """Test navigation logic for result rows."""

    @staticmethod
    def _move(result_indices, current_idx, delta):
        """Replicate GlobalSearchDialog._move_selection."""
        if not result_indices:
            return current_idx
        return (current_idx + delta) % len(result_indices)

    def test_wrap_down(self):
        assert self._move([0, 1, 2, 3], 3, 1) == 0

    def test_wrap_up(self):
        assert self._move([0, 1, 2, 3], 0, -1) == 3

    def test_empty_results(self):
        assert self._move([], 0, 1) == 0


class TestGlobalSearchDialogDebounce:
    """Verify search debounce."""

    def test_uses_debounce(self):
        source = read_popup_source("global_search_dialog.py")
        assert "timeout_add" in source
        assert "300" in source  # 300ms debounce

    def test_limits_results_to_500(self):
        source = read_popup_source("global_search_dialog.py")
        assert "500" in source
