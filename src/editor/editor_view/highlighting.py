"""Style scheme generation for GtkSourceView."""

import os

from gi.repository import GtkSource

from shared.settings import get_setting

# Directory for generated GtkSourceView style scheme files
_SCHEME_DIR = os.path.join(os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp", "zen-ide-schemes")


def _cursor_scheme_fg(editor_bg: str) -> str:
    """Return cursor foreground for the style scheme.

    When ``wide_cursor`` is active the native GtkSourceView caret must be
    invisible so only the custom block cursor shows.
    """
    if get_setting("wide_cursor", False):
        return editor_bg  # same as background → invisible
    return "fg"


def _generate_style_scheme(theme) -> str:
    """Generate a GtkSourceView style scheme XML from theme syntax colors.

    Returns the scheme id string (e.g. 'zen-dracula').
    """
    from shared.utils import contrast_color

    os.makedirs(_SCHEME_DIR, exist_ok=True)
    scheme_id = f"zen-{theme.name}"

    editor_bg = theme.main_bg
    line_bg = theme.line_number_bg
    sel_fg = contrast_color(theme.selection_bg)
    ws_color = get_setting("editor.whitespace_color", "") or theme.fg_dim
    ws_alpha = get_setting("editor.whitespace_alpha", -1)
    if 0.0 <= ws_alpha <= 1.0:
        ws_color = ws_color.lstrip("#")[:6] + f"{int(ws_alpha * 255):02x}"
        ws_color = f"#{ws_color}"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<style-scheme id="{scheme_id}" name="Zen {theme.display_name}" version="1.0">
  <color name="bg" value="{editor_bg}"/>
  <color name="fg" value="{theme.fg_color}"/>
  <color name="dim" value="{theme.fg_dim}"/>
  <color name="sel" value="{theme.selection_bg}"/>
  <color name="line_bg" value="{line_bg}"/>
  <color name="line_fg" value="{theme.line_number_fg}"/>

  <!-- Editor chrome -->
  <style name="text" foreground="fg" background="bg"/>
  <style name="selection" foreground="{sel_fg}" background="sel"/>
  <style name="cursor" foreground="{_cursor_scheme_fg(editor_bg)}"/>
  <style name="current-line" background="{theme.hover_bg}"/>
  <style name="line-numbers" foreground="line_fg" background="bg"/>
  <style name="right-margin" foreground="dim"/>
  <style name="bracket-match" foreground="fg" background="sel" bold="true"/>
  <style name="bracket-mismatch" foreground="{theme.get_syntax_color("syntax_string")}" background="bg" underline="true"/>
  <style name="search-match" background="{theme.search_match_bg or theme.selection_bg}"/>
  <style name="draw-spaces" foreground="{ws_color}"/>

  <!-- Syntax highlighting -->
  <style name="def:keyword" foreground="{theme.syntax_keyword}" bold="false"/>
  <style name="def:type" foreground="{theme.syntax_class}" bold="false"/>
  <style name="def:function" foreground="{theme.syntax_function}"/>
  <style name="def:string" foreground="{theme.syntax_string}"/>
  <style name="def:comment" foreground="{theme.syntax_comment}" italic="true"/>
  <style name="def:doc-comment" foreground="{theme.get_syntax_color("syntax_doc_comment")}" italic="true"/>
  <style name="def:doc-comment-element" foreground="{theme.get_syntax_color("syntax_doc_comment")}" bold="true"/>
  <style name="def:number" foreground="{theme.syntax_number}"/>
  <style name="def:floating-point" foreground="{theme.syntax_number}"/>
  <style name="def:decimal" foreground="{theme.syntax_number}"/>
  <style name="def:base-n-integer" foreground="{theme.syntax_number}"/>
  <style name="def:boolean" foreground="{theme.get_syntax_color("syntax_boolean")}"/>
  <style name="def:constant" foreground="{theme.get_syntax_color("syntax_constant")}"/>
  <style name="def:operator" foreground="{theme.syntax_operator}"/>
  <style name="def:special-char" foreground="{theme.get_syntax_color("syntax_string_escape")}"/>
  <style name="def:special-constant" foreground="{theme.get_syntax_color("syntax_constant")}"/>
  <style name="def:identifier" foreground="{theme.get_syntax_color("syntax_variable")}"/>
  <style name="def:preprocessor" foreground="{theme.syntax_keyword}"/>
  <style name="def:builtin" foreground="{theme.syntax_function}"/>
  <style name="def:statement" foreground="{theme.get_syntax_color("syntax_keyword_control")}"/>
  <style name="def:note" foreground="{theme.accent_color}" bold="true"/>
  <style name="def:error" foreground="{theme.get_syntax_color("syntax_string")}" underline="true"/>
  <style name="def:warning" foreground="{theme.syntax_number}" underline="true"/>
  <style name="def:net-address" foreground="{theme.syntax_function}" underline="true"/>
  <style name="def:regex" foreground="{theme.get_syntax_color("syntax_regex")}"/>

  <!-- JavaScript / TypeScript / JSX overrides (many styles lack def:* fallback) -->
  <style name="js:keyword" foreground="{theme.syntax_keyword}"/>
  <style name="js:built-in-constructor" foreground="{theme.syntax_class}"/>
  <style name="js:built-in-function" foreground="{theme.syntax_function}"/>
  <style name="js:built-in-method" foreground="{theme.syntax_function}"/>
  <style name="js:built-in-object" foreground="{theme.syntax_function}"/>
  <style name="js:identifier" foreground="{theme.fg_color}"/>
  <style name="js:template-placeholder" foreground="{theme.get_syntax_color("syntax_variable")}"/>
  <style name="jsx:element" foreground="{theme.syntax_keyword}"/>
  <style name="jsx:attribute-expression" foreground="{theme.get_syntax_color("syntax_variable")}"/>
  <style name="jsx:child-expression" foreground="{theme.get_syntax_color("syntax_variable")}"/>
  <style name="jsx:spread-attribute" foreground="{theme.syntax_operator}"/>
  <style name="typescript:decorator" foreground="{theme.syntax_keyword}" italic="true"/>
  <style name="typescript:decorator-operator" foreground="{theme.syntax_keyword}" italic="true"/>
  <style name="typescript:type-expression" foreground="{theme.syntax_class}"/>
  <style name="typescript:type-annotation" foreground="{theme.syntax_class}"/>
  <style name="typescript:interface-declaration" foreground="{theme.syntax_class}"/>
  <style name="typescript:enum-declaration" foreground="{theme.syntax_class}"/>
  <style name="typescript:type-alias-declaration" foreground="{theme.syntax_class}"/>
  <style name="typescript:optional-modifier" foreground="{theme.syntax_operator}"/>
  <style name="typescript:non-null-assertion-operator" foreground="{theme.syntax_operator}"/>
  <style name="typescript:union-intersection-type-operator" foreground="{theme.syntax_operator}"/>
  <style name="typescript:mapped-type-modifier-prefix" foreground="{theme.syntax_keyword}"/>
  <style name="typescript:ambient-declaration" foreground="{theme.syntax_keyword}"/>
  <style name="typescript:module-declaration" foreground="{theme.syntax_keyword}"/>
  <style name="typescript:namespace-declaration" foreground="{theme.syntax_keyword}"/>
  <style name="typescript:type-keyword" foreground="{theme.syntax_keyword}"/>
  <style name="typescript:basic-type" foreground="{theme.syntax_class}"/>
  <style name="typescript:built-in-library-type" foreground="{theme.syntax_class}"/>
  <style name="typescript:bracket-type-operator" foreground="{theme.syntax_operator}"/>
  <style name="typescript:conditional-type-operator" foreground="{theme.syntax_operator}"/>
  <style name="typescript:definite-assignment-assertion" foreground="{theme.syntax_operator}"/>
  <style name="typescript:object-type-literal" foreground="{theme.syntax_class}"/>
  <style name="typescript:tuple-type-literal" foreground="{theme.syntax_class}"/>
  <style name="typescript:type-arguments-list" foreground="{theme.syntax_class}"/>
  <style name="typescript:type-parameters-list" foreground="{theme.syntax_class}"/>
  <style name="typescript:global-augmentation" foreground="{theme.syntax_keyword}"/>

  <!-- Python-specific overrides (class-name maps to def:function by default) -->
  <style name="python:special-variable" foreground="{theme.syntax_keyword}"/>
  <style name="python3:special-variable" foreground="{theme.syntax_keyword}"/>
  <style name="python:class-name" foreground="{theme.syntax_class}"/>
  <style name="python3:class-name" foreground="{theme.syntax_class}"/>
  <style name="python:function-name" foreground="{theme.syntax_function}"/>
  <style name="python3:function-name" foreground="{theme.syntax_function}"/>
  <style name="python:decorator" foreground="{theme.syntax_keyword}" italic="true"/>
  <style name="python3:decorator" foreground="{theme.syntax_keyword}" italic="true"/>
  <style name="python:builtin-object" foreground="{theme.syntax_class}"/>
  <style name="python3:builtin-object" foreground="{theme.syntax_class}"/>
  <style name="python:builtin-function" foreground="{theme.syntax_function}"/>
  <style name="python3:builtin-function" foreground="{theme.syntax_function}"/>
</style-scheme>
"""
    path = os.path.join(_SCHEME_DIR, f"{scheme_id}.xml")
    with open(path, "w") as f:
        f.write(xml)

    # Register scheme directory with GtkSourceView
    scheme_manager = GtkSource.StyleSchemeManager.get_default()
    search_path = scheme_manager.get_search_path()
    if _SCHEME_DIR not in search_path:
        scheme_manager.prepend_search_path(_SCHEME_DIR)
    else:
        # Force reload by resetting search path
        scheme_manager.set_search_path(search_path)

    return scheme_id
