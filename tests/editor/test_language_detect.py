"""Tests for editor.langs.language_detect — mapping dicts and detect_language logic."""

from unittest.mock import MagicMock, patch

import pytest

from editor.langs.language_detect import _EXT_TO_LANG, _NAME_TO_LANG, detect_language


# ---------------------------------------------------------------------------
# Tests for _NAME_TO_LANG mapping
# ---------------------------------------------------------------------------
class TestNameToLang:
    def test_makefile_variants(self):
        assert _NAME_TO_LANG["Makefile"] == "makefile"
        assert _NAME_TO_LANG["makefile"] == "makefile"
        assert _NAME_TO_LANG["GNUmakefile"] == "makefile"

    def test_dockerfile(self):
        assert _NAME_TO_LANG["Dockerfile"] == "dockerfile"

    def test_cmake(self):
        assert _NAME_TO_LANG["CMakeLists.txt"] == "cmake"

    def test_unknown_name_not_present(self):
        assert "README.md" not in _NAME_TO_LANG


# ---------------------------------------------------------------------------
# Tests for _EXT_TO_LANG mapping
# ---------------------------------------------------------------------------
class TestExtToLang:
    @pytest.mark.parametrize(
        "ext, expected",
        [
            (".py", "python3"),
            (".js", "javascript"),
            (".ts", "typescript"),
            (".json", "json"),
            (".yaml", "yaml"),
            (".yml", "yaml"),
            (".md", "markdown"),
            (".html", "html"),
            (".css", "css"),
            (".c", "c"),
            (".cpp", "cpp"),
            (".h", "c"),
            (".rs", "rust"),
            (".go", "go"),
            (".rb", "ruby"),
            (".sh", "sh"),
            (".bash", "sh"),
            (".sql", "sql"),
            (".xml", "xml"),
            (".toml", "toml"),
            (".tf", "hcl"),
            (".java", "java"),
            (".kt", "kotlin"),
            (".swift", "swift"),
            (".lua", "lua"),
            (".r", "r"),
        ],
    )
    def test_extension_mapping(self, ext, expected):
        assert _EXT_TO_LANG[ext] == expected

    def test_unknown_ext_not_present(self):
        assert ".xyz" not in _EXT_TO_LANG


# ---------------------------------------------------------------------------
# Tests for detect_language() — mocked GTK
# ---------------------------------------------------------------------------
class TestDetectLanguage:
    """Verify fallback logic without requiring a real GTK installation."""

    def _mock_setup(self):
        """Return (mock_lang_manager, mock_language) pair."""
        mock_lang = MagicMock()
        mock_lang.get_id.return_value = "python3"

        mock_mgr = MagicMock()
        mock_mgr.guess_language.return_value = None
        mock_mgr.get_language.return_value = None
        return mock_mgr, mock_lang

    @patch("editor.langs.language_detect.Gio.content_type_guess", return_value=("text/x-python", True))
    @patch("editor.langs.language_detect.GtkSource.LanguageManager.get_default")
    def test_content_type_match(self, mock_get_default, mock_guess):
        mock_mgr, mock_lang = self._mock_setup()
        mock_mgr.guess_language.return_value = mock_lang
        mock_get_default.return_value = mock_mgr

        result = detect_language("/some/file.py")
        assert result is mock_lang
        mock_mgr.guess_language.assert_called_once()

    @patch("editor.langs.language_detect.Gio.content_type_guess", return_value=(None, False))
    @patch("editor.langs.language_detect.GtkSource.LanguageManager.get_default")
    def test_filename_fallback(self, mock_get_default, mock_guess):
        mock_mgr, mock_lang = self._mock_setup()
        mock_mgr.get_language.side_effect = lambda lid: mock_lang if lid == "makefile" else None
        mock_get_default.return_value = mock_mgr

        result = detect_language("/project/Makefile")
        assert result is mock_lang

    @patch("editor.langs.language_detect.Gio.content_type_guess", return_value=(None, False))
    @patch("editor.langs.language_detect.GtkSource.LanguageManager.get_default")
    def test_extension_fallback(self, mock_get_default, mock_guess):
        mock_mgr, mock_lang = self._mock_setup()
        mock_mgr.get_language.side_effect = lambda lid: mock_lang if lid == "rust" else None
        mock_get_default.return_value = mock_mgr

        result = detect_language("/code/main.rs")
        assert result is mock_lang

    @patch("editor.langs.language_detect.Gio.content_type_guess", return_value=(None, False))
    @patch("editor.langs.language_detect.GtkSource.LanguageManager.get_default")
    def test_returns_none_for_unknown(self, mock_get_default, mock_guess):
        mock_mgr, _ = self._mock_setup()
        mock_get_default.return_value = mock_mgr

        result = detect_language("/data/file.xyz")
        assert result is None

    @patch("editor.langs.language_detect.Gio.content_type_guess", return_value=("text/plain", True))
    @patch("editor.langs.language_detect.GtkSource.LanguageManager.get_default")
    def test_content_type_miss_falls_to_extension(self, mock_get_default, mock_guess):
        """content_type exists but guess_language returns None → fall to ext."""
        mock_mgr, mock_lang = self._mock_setup()
        mock_mgr.guess_language.return_value = None
        mock_mgr.get_language.side_effect = lambda lid: mock_lang if lid == "go" else None
        mock_get_default.return_value = mock_mgr

        result = detect_language("/src/main.go")
        assert result is mock_lang

    @patch("editor.langs.language_detect.Gio.content_type_guess", return_value=(None, False))
    @patch("editor.langs.language_detect.GtkSource.LanguageManager.get_default")
    def test_case_insensitive_extension(self, mock_get_default, mock_guess):
        """Extensions are lowercased before lookup."""
        mock_mgr, mock_lang = self._mock_setup()
        mock_mgr.get_language.side_effect = lambda lid: mock_lang if lid == "python3" else None
        mock_get_default.return_value = mock_mgr

        result = detect_language("/code/script.PY")
        assert result is mock_lang
