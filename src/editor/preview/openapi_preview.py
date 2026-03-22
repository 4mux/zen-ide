"""
OpenAPI Preview for Zen IDE GTK version.
Renders OpenAPI/Swagger specs as a styled interactive preview.
Parses YAML/JSON specs and renders endpoints, schemas, and info as HTML.

Uses the same rendering backend hierarchy as MarkdownPreview:
  1. WebKitGTK (Linux) - full HTML/CSS via GObject introspection
  2. macOS native WKWebView (via PyObjC) - full HTML/CSS overlaid on GTK4
  3. GtkTextView (fallback) - text-only summary
"""

import json
import os
import platform

import yaml
from gi.repository import GLib, Gtk, Pango

from editor.preview.preview_scroll_mixin import SCROLL_SYNC_JS, PreviewScrollMixin
from gi_requirements import load_webkit
from themes import get_theme, subscribe_theme_change
from themes.theme_manager import get_setting

# --- Backend detection (same as markdown_preview) ---

WebKit = load_webkit()
_HAS_WEBKIT = WebKit is not None

_HAS_MACOS_WEBKIT = False
if not _HAS_WEBKIT and platform.system() == "Darwin":
    try:
        from editor.preview.macos_webkit_helpers import (
            _HAS_MACOS_WEBKIT as _mac_available,
        )
        from editor.preview.macos_webkit_helpers import (
            _NSURL,
            _NSApp,
            _NSMakeRect,
            _ScrollHandler,
            _WKWebView,
            _WKWebViewConfig,
        )

        _HAS_MACOS_WEBKIT = _mac_available
    except ImportError:
        pass


# HTTP method colors - derived from theme
def _method_colors():
    """Return HTTP method colors from the active theme."""
    theme = get_theme()
    return {
        "get": theme.term_blue,
        "post": theme.term_green,
        "put": theme.warning_color,
        "delete": theme.term_red,
        "patch": theme.term_cyan or theme.syntax_operator,
        "options": theme.accent_color,
        "head": theme.term_magenta,
    }


def is_openapi_content(text: str) -> bool:
    """Check if text content is an OpenAPI/Swagger spec."""
    if not text or not text.strip():
        return False
    stripped = text.strip()
    # YAML detection
    if stripped.startswith("openapi:") or stripped.startswith("swagger:"):
        return True
    # JSON detection
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            return isinstance(data, dict) and ("openapi" in data or "swagger" in data)
        except (json.JSONDecodeError, ValueError):
            return False
    # YAML with leading comments or document marker
    for line in stripped.split("\n")[:20]:
        line = line.strip()
        if line.startswith("#") or line == "---" or not line:
            continue
        if line.startswith("openapi:") or line.startswith("swagger:"):
            return True
        break
    return False


def _parse_spec(text: str) -> dict | None:
    """Parse OpenAPI spec from YAML or JSON text."""
    if not text or not text.strip():
        return None
    stripped = text.strip()
    try:
        if stripped.startswith("{"):
            return json.loads(stripped)
        return yaml.safe_load(stripped)
    except Exception:
        return None


def _resolve_internal_refs_with_doc(obj, full_doc: dict, seen: set | None = None):
    """Resolve internal #/ $ref pointers against the full source document."""
    if not isinstance(obj, dict):
        return obj
    if seen is None:
        seen = set()
    if "$ref" in obj and isinstance(obj["$ref"], str) and obj["$ref"].startswith("#"):
        ref_key = obj["$ref"]
        if ref_key in seen:
            return obj
        resolved = _resolve_ref(full_doc, ref_key)
        if resolved:
            seen.add(ref_key)
            return _resolve_internal_refs_with_doc(resolved, full_doc, seen)
        return obj
    for key, value in list(obj.items()):
        if isinstance(value, dict):
            obj[key] = _resolve_internal_refs_with_doc(value, full_doc, seen)
        elif isinstance(value, list):
            obj[key] = [
                _resolve_internal_refs_with_doc(item, full_doc, seen) if isinstance(item, dict) else item for item in value
            ]
    return obj


def _resolve_file_ref(ref: str, base_dir: str) -> dict | None:
    """Load and parse an external file $ref, optionally following a JSON pointer."""
    if "#" in ref:
        file_ref, pointer = ref.split("#", 1)
    else:
        file_ref, pointer = ref, None
    ref_path = os.path.normpath(os.path.join(base_dir, file_ref))
    try:
        with open(ref_path, "r", encoding="utf-8") as f:
            content = f.read()
        full_doc = _parse_spec(content)
        if full_doc and isinstance(full_doc, dict):
            resolved = full_doc
            if pointer:
                resolved = _resolve_ref(full_doc, "#" + pointer)
            # Resolve internal $refs against the full source document
            if pointer and isinstance(resolved, dict):
                resolved = _resolve_internal_refs_with_doc(resolved, full_doc)
            return resolved
    except Exception:
        pass
    return None


def _deep_resolve_refs(obj, base_dir: str, depth: int = 0):
    """Recursively resolve all external $ref references in a parsed spec tree.

    depth tracks file-resolution hops only (not object tree depth) to prevent
    circular-reference loops while still resolving deeply nested specs.
    """
    if not isinstance(obj, dict):
        return obj
    if "$ref" in obj and isinstance(obj["$ref"], str) and not obj["$ref"].startswith("#"):
        if depth > 10:
            return obj
        ref = obj["$ref"]
        file_part = ref.split("#")[0] if "#" in ref else ref
        new_base = os.path.normpath(os.path.join(base_dir, os.path.dirname(file_part)))
        resolved = _resolve_file_ref(ref, base_dir)
        if resolved is not None:
            return _deep_resolve_refs(resolved, new_base, depth + 1)
        return obj
    for key, value in list(obj.items()):
        if isinstance(value, dict):
            obj[key] = _deep_resolve_refs(value, base_dir, depth)
        elif isinstance(value, list):
            obj[key] = [_deep_resolve_refs(item, base_dir, depth) if isinstance(item, dict) else item for item in value]
    return obj


def _resolve_external_refs(spec: dict, base_dir: str | None) -> dict:
    """Resolve all external file $ref references throughout the spec."""
    if not spec or not isinstance(spec, dict) or not base_dir:
        return spec
    return _deep_resolve_refs(spec, base_dir)


def _build_openapi_css(theme) -> str:
    """Build CSS for the OpenAPI preview."""
    from fonts import get_font_settings

    md_settings = get_font_settings("markdown_preview")
    body_font = md_settings["family"]
    font_size = md_settings.get("size", 14)

    editor_settings = get_font_settings("editor")
    code_font = editor_settings["family"]
    mono_stack = f'"{code_font}", monospace'
    body_stack = f'"{body_font}", sans-serif'
    return f"""
    :root {{ color-scheme: dark; }}
    html {{ height: 100%; overflow-y: auto; }}
    body {{
        font-family: {body_stack};
        font-size: {font_size}px;
        line-height: 1.6;
        color: {theme.fg_color};
        background-color: {theme.main_bg};
        padding: 0;
        margin: 0;
        min-height: 100%;
    }}
    ::-webkit-scrollbar {{ width: 20px; background: transparent; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{
        background-color: {theme.fg_color}40;
        border-radius: 0;
        border: 3px solid transparent;
        background-clip: padding-box;
    }}
    ::-webkit-scrollbar-thumb:hover {{
        background-color: {theme.fg_color}66;
        border: 3px solid transparent;
        background-clip: padding-box;
    }}
    .api-header {{
        padding: 20px 24px;
        border-bottom: 1px solid {theme.border_color};
    }}
    .api-title {{
        font-size: 1.8em;
        font-weight: 700;
        margin: 0 0 8px 0;
        color: {theme.fg_color};
    }}
    .api-version {{
        display: inline-block;
        background: {theme.accent_color};
        color: {theme.main_bg};
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.8em;
        font-weight: 600;
        margin-left: 8px;
    }}
    .api-description {{
        color: {theme.fg_dim};
        margin-top: 8px;
        font-size: 0.95em;
    }}
    .api-servers {{
        margin-top: 8px;
        font-size: 0.85em;
        color: {theme.fg_dim};
    }}
    .api-servers code {{
        font-family: {mono_stack};
        background: {theme.panel_bg};
        padding: 2px 6px;
        border-radius: 3px;
        color: {theme.accent_color};
    }}
    .tag-group {{
        margin: 28px 0 16px 0;
    }}
    .tag-name {{
        font-size: 1.2em;
        font-weight: 600;
        padding: 12px 24px;
        color: {theme.fg_color};
        border-bottom: 1px solid {theme.border_color};
    }}
    .endpoint {{
        margin: 4px 16px;
        border: 1px solid {theme.border_color};
        border-radius: 6px;
        overflow: hidden;
    }}
    .endpoint-summary {{
        display: flex;
        align-items: center;
        padding: 10px 16px;
        gap: 12px;
        cursor: default;
    }}
    .method-badge {{
        font-family: {mono_stack};
        font-size: 0.75em;
        font-weight: 700;
        text-transform: uppercase;
        padding: 4px 10px;
        border-radius: 4px;
        min-width: 60px;
        text-align: center;
        color: #fff;
    }}
    .endpoint-path {{
        font-family: {mono_stack};
        font-size: 0.9em;
        color: {theme.fg_color};
        font-weight: 600;
    }}
    .endpoint-desc {{
        color: {theme.fg_dim};
        font-size: 0.85em;
        flex: 1;
    }}
    .endpoint-details {{
        padding: 12px 16px;
        border-top: 1px solid {theme.border_color};
        background: {theme.panel_bg};
        display: none;
    }}
    .endpoint.open .endpoint-details {{ display: block; }}
    .detail-section {{
        margin: 16px 0 12px 0;
    }}
    .detail-section h4 {{
        font-size: 0.85em;
        font-weight: 600;
        color: {theme.fg_dim};
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin: 12px 0 8px 0;
    }}
    .param-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.85em;
        table-layout: fixed;
    }}
    .param-table th:nth-child(1), .param-table td:nth-child(1) {{ width: 25%; }}
    .param-table th:nth-child(2), .param-table td:nth-child(2) {{ width: 8%; }}
    .param-table th:nth-child(3), .param-table td:nth-child(3) {{ width: 12%; }}
    .param-table th:nth-child(4), .param-table td:nth-child(4) {{ width: 55%; }}
    .param-table th {{
        text-align: left;
        padding: 4px 8px;
        color: {theme.fg_dim};
        border-bottom: 1px solid {theme.border_color};
        font-weight: 600;
    }}
    .param-table td {{
        padding: 4px 8px;
        border-bottom: 1px solid {theme.border_color}40;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .param-name {{
        font-family: {mono_stack};
        color: {theme.accent_color};
    }}
    .param-required {{
        color: {theme.term_red};
        font-size: 0.8em;
    }}
    .param-type {{
        color: {theme.fg_dim};
        font-family: {mono_stack};
        font-size: 0.9em;
    }}
    .example-section {{
        margin: 6px 0 8px 0;
    }}
    .example-section summary {{
        cursor: pointer;
        font-size: 0.82em;
        font-weight: 600;
        color: {theme.accent_color};
        padding: 4px 0;
        user-select: none;
    }}
    .example-section summary:hover {{
        text-decoration: underline;
    }}
    .example-block {{
        font-family: {mono_stack};
        font-size: 0.8em;
        background: {theme.main_bg};
        padding: 8px 12px;
        border-radius: 4px;
        border: 1px solid {theme.border_color};
        white-space: pre-wrap;
        color: {theme.fg_dim};
        margin: 4px 0 0 0;
    }}
    .response-code {{
        font-family: {mono_stack};
        font-weight: 600;
        padding: 1px 6px;
        border-radius: 3px;
        font-size: 0.85em;
    }}
    .response-2xx {{ color: {theme.term_green}; }}
    .response-3xx {{ color: {theme.warning_color}; }}
    .response-4xx {{ color: {theme.term_red}; }}
    .response-5xx {{ color: {theme.term_red}; }}
    .schema-block {{
        font-family: {mono_stack};
        font-size: 0.8em;
        background: {theme.main_bg};
        padding: 8px 12px;
        border-radius: 4px;
        border: 1px solid {theme.border_color};
        white-space: pre-wrap;
        color: {theme.fg_dim};
    }}
    .schema-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.85em;
        margin: 4px 0 8px 0;
        table-layout: fixed;
    }}
    .schema-table th:nth-child(1), .schema-table td:nth-child(1) {{ width: 25%; }}
    .schema-table th:nth-child(2), .schema-table td:nth-child(2) {{ width: 12%; }}
    .schema-table th:nth-child(3), .schema-table td:nth-child(3) {{ width: 8%; }}
    .schema-table th:nth-child(4), .schema-table td:nth-child(4) {{ width: 55%; }}
    .schema-table th {{
        text-align: left;
        padding: 4px 8px;
        color: {theme.fg_dim};
        border-bottom: 1px solid {theme.border_color};
        font-weight: 600;
    }}
    .schema-table td {{
        padding: 4px 8px;
        border-bottom: 1px solid {theme.border_color}40;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    .schema-table td:first-child {{
        white-space: nowrap;
    }}
    .schema-table tr.nested td {{
        color: {theme.fg_dim};
    }}
    .schema-toggle {{
        cursor: pointer;
        user-select: none;
        font-weight: 600;
        color: {theme.accent_color};
        white-space: nowrap;
    }}
    .schema-toggle:hover {{ text-decoration: underline; }}
    .schema-toggle::before {{
        display: inline-block;
        margin-right: 4px;
    }}
    tr.collapsed .schema-toggle::before {{ content: "▶"; }}
    tr:not(.collapsed) .schema-toggle::before {{ content: "▼"; }}
    .empty-state {{
        text-align: center;
        padding: 60px 24px;
        color: {theme.fg_dim};
    }}
    .empty-state .icon {{ font-size: 3em; margin-bottom: 16px; }}
    .empty-state .title {{ font-size: 1.2em; font-weight: 600; margin-bottom: 8px; color: {theme.fg_color}; }}
    .deprecated {{ text-decoration: line-through; opacity: 0.6; }}
    """


_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>{css}</style>
<script>
function toggleEndpoint(el) {{
    el.closest('.endpoint').classList.toggle('open');
}}
function toggleSchema(el) {{
    var row = el.closest('tr');
    var name = row.dataset.name;
    var table = row.closest('table');
    var rows = table.querySelectorAll('tr[data-name]');
    var isCollapsed = row.classList.toggle('collapsed');
    var depth = (name.match(/\\./g) || []).length;
    for (var i = 0; i < rows.length; i++) {{
        var r = rows[i];
        if (!r.dataset.name || !r.dataset.name.startsWith(name + '.')) continue;
        var childDepth = (r.dataset.name.match(/\\./g) || []).length;
        if (isCollapsed) {{
            r.style.display = 'none';
            r.classList.add('collapsed');
        }} else {{
            if (childDepth === depth + 1) {{
                r.style.display = '';
            }}
        }}
    }}
}}
</script>
</head>
<body>{body}</body>
</html>"""


def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _resolve_ref(spec: dict, ref: str) -> dict:
    """Resolve a $ref pointer in the spec."""
    if not ref.startswith("#/"):
        return {}
    parts = ref[2:].split("/")
    current = spec
    for part in parts:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return {}
    return current if isinstance(current, dict) else {}


def _schema_summary(schema: dict, spec: dict, depth: int = 0, indent: int = 0) -> str:
    """Generate a brief text summary of a JSON schema."""
    if not schema or depth > 5:
        return ""
    pad = "  " * indent
    inner = "  " * (indent + 1)
    if "$ref" in schema:
        resolved = _resolve_ref(spec, schema["$ref"])
        ref_name = schema["$ref"].split("/")[-1]
        if resolved and depth < 3:
            return f"{ref_name}: {_schema_summary(resolved, spec, depth + 1, indent)}"
        return ref_name
    schema_type = schema.get("type", "")
    if schema_type == "object":
        props = schema.get("properties", {})
        if props:
            fields = []
            for name, prop in list(props.items())[:10]:
                ptype = _schema_summary(prop, spec, depth + 1, indent + 1) or prop.get("type", "any")
                desc = prop.get("description", "")
                desc_str = f"  // {desc}" if desc else ""
                fields.append(f"{inner}{name}: {ptype}{desc_str}")
            result = "{\n" + ",\n".join(fields)
            if len(props) > 10:
                result += f",\n{inner}... ({len(props) - 10} more)"
            return result + f"\n{pad}}}"
        return "object"
    if schema_type == "array":
        items = schema.get("items", {})
        items_summary = _schema_summary(items, spec, depth + 1, indent) or "any"
        return f"[{items_summary}]"
    if "enum" in schema:
        vals = " | ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in schema["enum"][:6])
        return vals
    if schema_type:
        fmt = schema.get("format", "")
        return f"{schema_type}({fmt})" if fmt else schema_type
    # oneOf / anyOf / allOf
    for keyword in ("oneOf", "anyOf", "allOf"):
        if keyword in schema:
            parts = [_schema_summary(s, spec, depth + 1, indent) for s in schema[keyword][:4]]
            joiner = " | " if keyword != "allOf" else " & "
            return joiner.join(p for p in parts if p)
    return ""


def _merge_allof(schemas: list, spec: dict) -> dict:
    """Merge allOf schemas into a single combined schema."""
    merged: dict = {"type": "object", "properties": {}, "required": []}
    for s in schemas:
        if "$ref" in s:
            s = _resolve_ref(spec, s["$ref"]) or s
        if "allOf" in s:
            s = _merge_allof(s["allOf"], spec)
        merged["properties"].update(s.get("properties", {}))
        merged["required"].extend(s.get("required", []))
        if s.get("description") and not merged.get("description"):
            merged["description"] = s["description"]
    return merged


def _schema_to_rows(schema: dict, spec: dict, required_set: set | None = None, prefix: str = "", depth: int = 0) -> list:
    """Flatten a JSON schema into table rows: [(name, type_str, required, description), ...]."""
    if not schema or depth > 5:
        return []
    if "$ref" in schema:
        resolved = _resolve_ref(spec, schema["$ref"])
        if resolved and depth < 4:
            return _schema_to_rows(resolved, spec, resolved.get("required"), prefix, depth + 1)
        return []
    # Handle allOf composition
    if "allOf" in schema:
        merged = _merge_allof(schema["allOf"], spec)
        return _schema_to_rows(merged, spec, required_set, prefix, depth)
    # Handle oneOf/anyOf - show rows from each variant
    for kw in ("oneOf", "anyOf"):
        if kw in schema:
            rows = []
            for s in schema[kw][:4]:
                rows.extend(_schema_to_rows(s, spec, required_set, prefix, depth + 1))
            return rows
    schema_type = schema.get("type", "")
    # Treat schemas with properties as objects even without explicit type
    has_properties = bool(schema.get("properties"))
    if required_set is None:
        required_set = set(schema.get("required", []))
    if schema_type == "object" or has_properties:
        props = schema.get("properties", {})
        req = set(schema.get("required", [])) if schema.get("required") else required_set
        rows = []
        for name, prop in list(props.items())[:20]:
            if "$ref" in prop:
                resolved = _resolve_ref(spec, prop["$ref"])
                if resolved:
                    prop = resolved
            # Handle allOf inside property
            if "allOf" in prop:
                prop = _merge_allof(prop["allOf"], spec)
            full_name = f"{prefix}{name}" if prefix else name
            ptype = prop.get("type", "")
            fmt = prop.get("format", "")
            if "enum" in prop:
                vals = ", ".join(f'"{v}"' if isinstance(v, str) else str(v) for v in prop["enum"][:6])
                type_str = f"enum({vals})"
            elif ptype == "array":
                items = prop.get("items", {})
                if "$ref" in items:
                    ref_resolved = _resolve_ref(spec, items["$ref"])
                    item_type = items["$ref"].split("/")[-1]
                    if ref_resolved:
                        items = ref_resolved
                else:
                    item_type = items.get("type", "any")
                type_str = f"array[{item_type}]"
            elif ptype == "object" or prop.get("properties"):
                type_str = "object"
            else:
                type_str = f"{ptype}({fmt})" if fmt else (ptype or "any")
            # oneOf / anyOf
            for kw in ("oneOf", "anyOf"):
                if kw in prop:
                    parts = []
                    for s in prop[kw][:4]:
                        if "$ref" in s:
                            parts.append(s["$ref"].split("/")[-1])
                        else:
                            parts.append(s.get("type", ""))
                    type_str = " | ".join(p for p in parts if p)
            is_req = name in req
            desc = prop.get("description", "")
            rows.append((full_name, type_str, is_req, desc))
            # Recurse into nested objects (check properties, not just type)
            if prop.get("properties") and depth < 3:
                nested = _schema_to_rows(prop, spec, None, f"{full_name}.", depth + 1)
                rows.extend(nested)
            # Recurse into additionalProperties if it's an object schema
            elif prop.get("additionalProperties") and isinstance(prop["additionalProperties"], dict) and depth < 3:
                add_props = prop["additionalProperties"]
                if "$ref" in add_props:
                    add_props = _resolve_ref(spec, add_props["$ref"]) or add_props
                if add_props.get("properties"):
                    key_name = f"{full_name}.<key>"
                    add_type = add_props.get("type", "object")
                    add_desc = add_props.get("description", "")
                    rows.append((key_name, add_type, False, add_desc))
                    nested = _schema_to_rows(add_props, spec, None, f"{key_name}.", depth + 1)
                    rows.extend(nested)
            # Recurse into array items if they're objects
            if ptype == "array":
                arr_items = prop.get("items", {})
                if "$ref" in arr_items:
                    arr_items = _resolve_ref(spec, arr_items["$ref"]) or arr_items
                if "allOf" in arr_items:
                    arr_items = _merge_allof(arr_items["allOf"], spec)
                if arr_items.get("properties") and depth < 3:
                    nested = _schema_to_rows(arr_items, spec, None, f"{full_name}[].", depth + 1)
                    rows.extend(nested)
        return rows
    if schema_type == "array":
        items = schema.get("items", {})
        if "$ref" in items:
            items = _resolve_ref(spec, items["$ref"]) or items
        if "allOf" in items:
            items = _merge_allof(items["allOf"], spec)
        if items.get("properties"):
            return _schema_to_rows(items, spec, None, prefix, depth + 1)
        return []
    return []


def _compose_example(schema: dict, spec: dict, depth: int = 0) -> object:
    """Auto-compose an example JSON value from a schema."""
    if not schema or depth > 5:
        return None
    if "$ref" in schema:
        resolved = _resolve_ref(spec, schema["$ref"])
        return _compose_example(resolved, spec, depth + 1) if resolved else None
    if "allOf" in schema:
        merged = _merge_allof(schema["allOf"], spec)
        return _compose_example(merged, spec, depth)
    if "example" in schema:
        return schema["example"]
    schema_type = schema.get("type", "")
    has_properties = bool(schema.get("properties"))
    if schema_type == "object" or has_properties:
        obj = {}
        for name, prop in list(schema.get("properties", {}).items())[:20]:
            if "$ref" in prop:
                prop = _resolve_ref(spec, prop["$ref"]) or prop
            if "allOf" in prop:
                prop = _merge_allof(prop["allOf"], spec)
            val = _compose_example(prop, spec, depth + 1)
            if val is not None:
                obj[name] = val
            else:
                # Generate a placeholder based on type
                pt = prop.get("type", "")
                if "enum" in prop:
                    obj[name] = prop["enum"][0] if prop["enum"] else ""
                elif pt == "string":
                    obj[name] = prop.get("format", "string")
                elif pt == "integer":
                    obj[name] = 0
                elif pt == "number":
                    obj[name] = 0.0
                elif pt == "boolean":
                    obj[name] = True
                elif pt == "array":
                    items = prop.get("items", {})
                    if "$ref" in items:
                        items = _resolve_ref(spec, items["$ref"]) or items
                    item_ex = _compose_example(items, spec, depth + 1)
                    obj[name] = [item_ex] if item_ex is not None else []
                elif prop.get("properties"):
                    obj[name] = _compose_example(prop, spec, depth + 1) or {}
        return obj
    if schema_type == "array":
        items = schema.get("items", {})
        if "$ref" in items:
            items = _resolve_ref(spec, items["$ref"]) or items
        item_ex = _compose_example(items, spec, depth + 1)
        return [item_ex] if item_ex is not None else []
    if "enum" in schema:
        return schema["enum"][0] if schema["enum"] else ""
    if schema_type == "string":
        return schema.get("format", "string")
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return True
    return None


def _render_schema_table(schema: dict, spec: dict) -> str:
    """Render a JSON schema as an HTML table with Name, Type, Required, Description columns."""
    rows = _schema_to_rows(schema, spec)
    if not rows:
        summary = _schema_summary(schema, spec)
        if summary:
            return f'<pre class="schema-block">{_html_escape(summary)}</pre>'
        return ""
    # Determine which rows are parents (have nested children)
    names = [r[0] for r in rows]
    parent_set = set()
    for n in names:
        parts = n.split(".")
        for i in range(1, len(parts)):
            parent_set.add(".".join(parts[:i]))
    html = '<table class="schema-table"><tr><th>Name</th><th>Type</th><th>Req</th><th>Description</th></tr>'
    for name, type_str, required, desc in rows:
        is_nested = "." in name
        is_parent = name in parent_set
        nested_class = " nested" if is_nested else ""
        collapsed_class = " collapsed" if is_parent else ""
        hidden = ' style="display:none"' if is_nested else ""
        display_name = name.split(".")[-1] if is_nested else name
        indent_level = name.count(".")
        indent_pad = "&nbsp;&nbsp;" * indent_level
        req_mark = '<span class="param-required">✓</span>' if required else ""
        html += f'<tr class="{nested_class}{collapsed_class}" data-name="{_html_escape(name)}"{hidden}>'
        if is_parent:
            html += f'<td>{indent_pad}<span class="schema-toggle" onclick="toggleSchema(this)">{_html_escape(display_name)}</span></td>'
        else:
            html += f'<td>{indent_pad}<span class="param-name">{_html_escape(display_name)}</span></td>'
        html += f'<td class="param-type">{_html_escape(type_str)}</td>'
        html += f'<td style="text-align:center">{req_mark}</td>'
        html += f"<td>{_html_escape(desc)}</td></tr>"
    html += "</table>"
    # Auto-compose example as collapsible section
    example = _compose_example(schema, spec)
    if example is not None:
        try:
            example_json = json.dumps(example, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            example_json = str(example)
        html += '<details class="example-section"><summary>Example</summary>'
        html += f'<pre class="example-block">{_html_escape(example_json)}</pre>'
        html += "</details>"
    return html


def _render_parameters(params: list, spec: dict) -> str:
    """Render parameters as an HTML table."""
    if not params:
        return ""
    html = '<div class="detail-section"><h4>Parameters</h4>'
    html += '<table class="param-table"><tr><th>Name</th><th>In</th><th>Type</th><th>Description</th></tr>'
    for p in params:
        if "$ref" in p:
            p = _resolve_ref(spec, p["$ref"])
        name = _html_escape(p.get("name", ""))
        location = _html_escape(p.get("in", ""))
        required = p.get("required", False)
        schema = p.get("schema", {})
        ptype = _html_escape(_schema_summary(schema, spec) or schema.get("type", ""))
        desc = _html_escape(p.get("description", ""))
        req_badge = ' <span class="param-required">*</span>' if required else ""
        html += f'<tr><td><span class="param-name">{name}</span>{req_badge}</td>'
        html += f'<td>{location}</td><td class="param-type">{ptype}</td>'
        html += f"<td>{desc}</td></tr>"
    html += "</table></div>"
    return html


def _render_request_body(body: dict, spec: dict) -> str:
    """Render request body section."""
    if not body:
        return ""
    if "$ref" in body:
        body = _resolve_ref(spec, body["$ref"])
    content = body.get("content", {})
    html = '<div class="detail-section"><h4>Request Body</h4>'
    desc = body.get("description", "")
    if desc:
        html += f"<p>{_html_escape(desc)}</p>"
    for media_type, media_obj in content.items():
        schema = media_obj.get("schema", {})
        table_html = _render_schema_table(schema, spec)
        if table_html:
            html += f"<div><em>{_html_escape(media_type)}</em></div>"
            html += table_html
    html += "</div>"
    return html


def _render_responses(responses: dict, spec: dict) -> str:
    """Render responses section."""
    if not responses:
        return ""
    html = '<div class="detail-section"><h4>Responses</h4>'
    for code, resp in sorted(responses.items()):
        if "$ref" in resp:
            resp = _resolve_ref(spec, resp["$ref"])
        css_class = f"response-{str(code)[0]}xx" if str(code)[0].isdigit() else ""
        desc = _html_escape(resp.get("description", ""))
        html += (
            f'<div style="margin-bottom:8px"><span class="response-code {css_class}">{_html_escape(str(code))}</span> {desc}'
        )
        content = resp.get("content", {})
        for media_type, media_obj in content.items():
            schema = media_obj.get("schema", {})
            table_html = _render_schema_table(schema, spec)
            if table_html:
                html += f'<div style="margin-top:4px"><em>{_html_escape(media_type)}</em></div>'
                html += table_html
        html += "</div>"
    html += "</div>"
    return html


def _render_spec_html(spec: dict) -> str:
    """Render the full OpenAPI spec as HTML body."""
    if not spec or not isinstance(spec, dict):
        return '<div class="empty-state"><div class="icon">📋</div><div class="title">Not a valid OpenAPI spec</div><div>Edit the file to add a valid OpenAPI or Swagger definition.</div></div>'

    html_parts = []

    # API Info header
    info = spec.get("info", {})
    title = _html_escape(info.get("title", "Untitled API"))
    version = _html_escape(info.get("version", ""))
    description = _html_escape(info.get("description", ""))

    header = f'<div class="api-header"><div class="api-title">{title}'
    if version:
        header += f'<span class="api-version">{version}</span>'
    header += "</div>"
    if description:
        header += f'<div class="api-description">{description}</div>'

    # Servers
    servers = spec.get("servers", [])
    if servers:
        header += '<div class="api-servers">Servers: '
        header += ", ".join(f"<code>{_html_escape(s.get('url', ''))}</code>" for s in servers[:5])
        header += "</div>"
    # Swagger 2.0 host/basePath
    elif spec.get("host"):
        scheme = (spec.get("schemes") or ["https"])[0]
        base = spec.get("basePath", "")
        header += f'<div class="api-servers">Base URL: <code>{_html_escape(scheme)}://{_html_escape(spec["host"])}{_html_escape(base)}</code></div>'

    header += "</div>"
    html_parts.append(header)

    # Collect endpoints grouped by tag
    paths = spec.get("paths", {})
    tagged: dict[str, list] = {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        # Resolve $ref at path-item level (internal or leftover external)
        if "$ref" in path_item:
            ref_val = path_item["$ref"]
            if isinstance(ref_val, str) and ref_val.startswith("#"):
                path_item = _resolve_ref(spec, ref_val)
                if not isinstance(path_item, dict):
                    continue
        for method in ("get", "post", "put", "delete", "patch", "options", "head"):
            if method not in path_item:
                continue
            op = path_item[method]
            if not isinstance(op, dict):
                continue
            tags = op.get("tags", ["default"])
            for tag in tags:
                tagged.setdefault(tag, []).append((method, path, op, path_item))

    # Render each tag group
    for tag_name, endpoints in tagged.items():
        group = f'<div class="tag-group"><div class="tag-name">{_html_escape(tag_name)}</div>'
        for method, path, op, path_item in endpoints:
            color = _method_colors().get(method, get_theme().fg_dim)
            summary = _html_escape(op.get("summary", ""))
            desc = _html_escape(op.get("description", ""))
            deprecated = op.get("deprecated", False)
            dep_class = " deprecated" if deprecated else ""

            group += '<div class="endpoint">'
            group += f'<div class="endpoint-summary{dep_class}" onclick="toggleEndpoint(this)">'
            group += f'<span class="method-badge" style="background:{color}">{method.upper()}</span>'
            group += f'<span class="endpoint-path">{_html_escape(path)}</span>'
            if summary:
                group += f'<span class="endpoint-desc">{summary}</span>'
            group += "</div>"

            # Details section
            group += '<div class="endpoint-details">'
            if desc:
                group += f"<p>{desc}</p>"

            # Parameters (path-level + operation-level)
            params = list(path_item.get("parameters", []))
            params.extend(op.get("parameters", []))
            group += _render_parameters(params, spec)

            # Request body (OpenAPI 3.x)
            if "requestBody" in op:
                group += _render_request_body(op["requestBody"], spec)

            # Responses
            group += _render_responses(op.get("responses", {}), spec)

            group += "</div></div>"  # endpoint-details, endpoint

        group += "</div>"  # tag-group
        html_parts.append(group)

    if not paths:
        html_parts.append(
            '<div class="empty-state"><div class="icon">📭</div>'
            '<div class="title">No paths defined</div>'
            "<div>Add paths to your OpenAPI spec to see them here.</div></div>"
        )

    return "\n".join(html_parts)


def _render_spec_text(spec: dict) -> str:
    """Render a plain-text summary of the spec for the textview fallback."""
    if not spec or not isinstance(spec, dict):
        return "Not a valid OpenAPI spec."

    lines = []
    info = spec.get("info", {})
    version = info.get("version", "?")
    version_str = version if version.startswith("v") else f"v{version}"
    lines.append(f"  {info.get('title', 'Untitled API')}  {version_str}")
    lines.append("=" * 50)
    desc = info.get("description", "")
    if desc:
        lines.append(desc)
        lines.append("")

    paths = spec.get("paths", {})
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        # Resolve $ref at path-item level (internal or leftover external)
        if "$ref" in path_item:
            ref_val = path_item["$ref"]
            if isinstance(ref_val, str) and ref_val.startswith("#"):
                path_item = _resolve_ref(spec, ref_val)
                if not isinstance(path_item, dict):
                    continue
        for method in ("get", "post", "put", "delete", "patch", "options", "head"):
            if method not in path_item:
                continue
            op = path_item[method]
            if not isinstance(op, dict):
                continue
            summary = op.get("summary", "")
            line = f"  {method.upper():8s} {path}"
            if summary:
                line += f"  — {summary}"
            lines.append(line)

            params = op.get("parameters", [])
            for p in params:
                pname = p.get("name", "?")
                ploc = p.get("in", "?")
                lines.append(f"           param: {pname} ({ploc})")

            responses = op.get("responses", {})
            for code in sorted(responses.keys()):
                rdesc = responses[code].get("description", "") if isinstance(responses[code], dict) else ""
                lines.append(f"           {code}: {rdesc}")
            lines.append("")

    if not paths:
        lines.append("  No paths defined.")

    return "\n".join(lines)


class _MacOSWebKitHelper:
    """Manages a native macOS WKWebView overlaid on a GTK4 widget area."""

    def __init__(self, on_scroll_fraction=None):
        self._on_scroll_fraction = on_scroll_fraction
        config = _WKWebViewConfig.alloc().init()

        # Register JS → Python message handler for reverse scroll sync
        if on_scroll_fraction:
            self._scroll_handler = _ScrollHandler.alloc().init()
            self._scroll_handler.callback = on_scroll_fraction
            uc = config.userContentController()
            uc.addScriptMessageHandler_name_(self._scroll_handler, "zenScrollSync")

        self._webview = _WKWebView.alloc().initWithFrame_configuration_(_NSMakeRect(0, 0, 1, 1), config)
        if self._webview is None:
            self._ns_window = None
            self._attached = False
            return
        self._webview.setValue_forKey_(False, "drawsBackground")
        self._webview.setHidden_(True)
        self._ns_window = None
        self._attached = False

    def attach(self, gtk_widget):
        if self._webview is None:
            return False
        self._ns_window = _NSApp.mainWindow()
        if not self._ns_window and _NSApp.windows():
            self._ns_window = _NSApp.windows()[0]
        if not self._ns_window:
            return False
        content_view = self._ns_window.contentView()
        content_view.addSubview_(self._webview)
        self._webview.setHidden_(False)
        self._attached = True
        return True

    def update_frame(self, x, y, width, height):
        if not self._attached or not self._ns_window:
            return
        cv = self._ns_window.contentView()
        cv_height = cv.frame().size.height
        ns_y = y if cv.isFlipped() else cv_height - y - height
        self._webview.setFrame_(_NSMakeRect(x, ns_y, width, height))

    def load_html(self, html):
        self._webview.loadHTMLString_baseURL_(html, _NSURL.URLWithString_("about:blank"))

    def scroll_by(self, dx, dy):
        js = f"window.scrollBy({dx},{dy});"
        self._webview.evaluateJavaScript_completionHandler_(js, None)

    def set_hidden(self, hidden):
        if self._webview:
            self._webview.setHidden_(hidden)

    def destroy(self):
        if self._webview:
            self._webview.removeFromSuperview()
            self._webview = None
        self._attached = False


class _SyncPlaceholder(Gtk.Widget):
    """Lightweight widget that calls a sync function on every snapshot."""

    def __init__(self, sync_func):
        super().__init__()
        self._sync_func = sync_func

    def do_snapshot(self, snapshot):
        w = self.get_width()
        h = self.get_height()
        if self._sync_func:
            self._sync_func(self, w, h)


class OpenAPIPreview(PreviewScrollMixin, Gtk.Box):
    """OpenAPI spec preview widget. Rendering backends:
    1. WebKitGTK (Linux) - full HTML/CSS
    2. macOS native WKWebView (PyObjC) - full HTML/CSS overlaid on GTK4
    3. GtkTextView (fallback) - text-only summary
    """

    _ZOOM_STEP = 0.1
    _ZOOM_MIN = 0.3
    _ZOOM_MAX = 3.0

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._init_scroll_sync()
        self._zoom_level = 1.0
        self._last_content = None
        self._last_file_path = None
        self._css_provider = None

        # Canvas backend is the default — native GTK scroll physics
        # (DrawingArea in ScrolledWindow, same architecture as MarkdownPreview).
        # Override via preview.backend setting to use "webkit_gtk" or "macos_webkit".
        backend_override = get_setting("preview.backend", "")
        if backend_override == "webkit_gtk" and _HAS_WEBKIT:
            self._backend = "webkit_gtk"
        elif backend_override == "macos_webkit" and _HAS_MACOS_WEBKIT:
            self._backend = "macos_webkit"
        else:
            self._backend = "canvas"
        self._create_ui()
        subscribe_theme_change(self._on_theme_change)
        from fonts import subscribe_font_change

        subscribe_font_change(self._on_font_change)

    def _create_ui(self):
        if self._backend == "canvas":
            self._create_canvas_ui()
        elif self._backend == "webkit_gtk":
            self._create_webkit_gtk_ui()
        elif self._backend == "macos_webkit":
            self._create_macos_webkit_ui()
        else:
            self._create_textview_ui()

    # -- Native Canvas --

    def _create_canvas_ui(self):
        """Create native MarkdownCanvas preview — pixel-perfect scroll sync."""
        from editor.preview.markdown_canvas import MarkdownCanvas

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        self.append(scrolled)

        canvas = MarkdownCanvas()
        scrolled.set_child(canvas)
        canvas.attach_to_scrolled_window(scrolled)

        # Shared scroll sync wiring (kinetic scrolling + value-changed signal)
        self._connect_canvas_scroll_sync(scrolled, canvas)

        # Apply theme
        theme = get_theme()
        self._apply_canvas_theme(theme)

        # Apply font
        from fonts import get_font_settings

        md_settings = get_font_settings("markdown_preview")
        font_family = md_settings["family"]
        font_size = md_settings.get("size", 14)
        self._canvas.set_font(font_family, font_size)

    def _apply_canvas_theme(self, theme):
        """Apply theme to MarkdownCanvas."""
        self._canvas.set_theme(
            fg=theme.fg_color,
            bg=theme.main_bg,
            code_bg=theme.panel_bg,
            accent=theme.accent_color,
            dim=theme.fg_dim,
            border=theme.border_color,
            selection_bg=theme.selection_bg,
        )

    # -- WebKitGTK (Linux) --

    def _create_webkit_gtk_ui(self):
        ucm = WebKit.UserContentManager()
        ucm.connect("script-message-received::zenScrollSync", self._on_webkit_script_message)
        ucm.register_script_message_handler("zenScrollSync")
        self.webview = WebKit.WebView.new_with_user_content_manager(ucm)
        self.webview.set_vexpand(True)
        self.webview.set_hexpand(True)

        settings = self.webview.get_settings()
        if hasattr(settings, "set_enable_developer_extras"):
            settings.set_enable_developer_extras(False)

        theme = get_theme()
        self._css_provider = Gtk.CssProvider()
        self._css_provider.load_from_data(f"webview {{ background-color: {theme.main_bg}; }}".encode())
        self.webview.get_style_context().add_provider(self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.append(self.webview)
        self._connect_webkit_scroll_sync(self.webview)

    # -- macOS native WKWebView (PyObjC) --

    def _create_macos_webkit_ui(self):
        self._placeholder = _SyncPlaceholder(self._on_placeholder_sync)
        self._placeholder.set_vexpand(True)
        self._placeholder.set_hexpand(True)
        self._placeholder.set_can_target(True)
        self._placeholder.set_focusable(True)
        self.append(self._placeholder)

        scroll_ctrl = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES | Gtk.EventControllerScrollFlags.KINETIC
        )
        scroll_ctrl.connect("scroll", self._on_macos_scroll)
        self._placeholder.add_controller(scroll_ctrl)

        self._macos_helper = _MacOSWebKitHelper(on_scroll_fraction=self._on_preview_scrolled)
        self._macos_attached = False
        self._pending_html = None

        self._placeholder.connect("realize", self._on_macos_realize)
        self._placeholder.connect("unrealize", self._on_macos_unrealize)
        self._placeholder.connect("map", lambda _w: self._macos_set_visible(True))
        self._placeholder.connect("unmap", lambda _w: self._macos_set_visible(False))

    def _on_macos_realize(self, _widget):
        GLib.timeout_add(200, self._try_attach_macos)

    def _try_attach_macos(self):
        if self._macos_attached:
            return False
        if self._macos_helper.attach(self._placeholder):
            self._macos_attached = True
            if self._pending_html:
                self._macos_helper.load_html(self._pending_html)
                self._pending_html = None
            self._placeholder.queue_draw()
        else:
            GLib.timeout_add(200, self._try_attach_macos)
        return False

    def _on_placeholder_sync(self, area, width, height):
        if not self._macos_attached:
            return
        root = area.get_root()
        if not root:
            return
        success, bounds = area.compute_bounds(root)
        if success:
            self._macos_helper.update_frame(bounds.get_x(), bounds.get_y(), width, height)

    def _on_macos_scroll(self, _ctrl, dx, dy):
        if self._macos_attached:
            from themes.theme_manager import get_setting

            speed = get_setting("scroll_speed", 0.4)
            px_per_unit = 50 * speed
            self._macos_helper.scroll_by(dx * px_per_unit, dy * px_per_unit)
        return True

    def _macos_set_visible(self, visible):
        if hasattr(self, "_macos_helper"):
            self._macos_helper.set_hidden(not visible)

    def _on_macos_unrealize(self, _widget):
        self._macos_helper.destroy()
        self._macos_attached = False

    # -- GtkTextView fallback --

    def _create_textview_ui(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        self.append(scrolled)

        self.text_view = Gtk.TextView()
        self.text_view.set_editable(False)
        self.text_view.set_focusable(False)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.set_monospace(True)
        self.text_view.set_margin_start(8)
        self.text_view.set_margin_end(8)
        self.text_view.set_margin_top(8)
        self.text_view.set_margin_bottom(8)

        self.buffer = self.text_view.get_buffer()
        scrolled.set_child(self.text_view)

        # Reverse scroll sync for textview fallback
        self._connect_textview_scroll_sync(scrolled)

        self._apply_styles()

    def _apply_styles(self):
        theme = get_theme()
        self._css_provider = Gtk.CssProvider()
        css = f"""
            textview text {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
            }}
        """
        self._css_provider.load_from_data(css.encode())
        self.text_view.get_style_context().add_provider(self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    # -- Public API --

    def zoom_in(self):
        self._zoom_level = min(self._zoom_level + self._ZOOM_STEP, self._ZOOM_MAX)
        self._apply_zoom()

    def zoom_out(self):
        self._zoom_level = max(self._zoom_level - self._ZOOM_STEP, self._ZOOM_MIN)
        self._apply_zoom()

    def zoom_reset(self):
        self._zoom_level = 1.0
        self._apply_zoom()

    def _apply_zoom(self):
        if self._backend == "canvas" and hasattr(self, "_canvas"):
            self._canvas._zoom_level = self._zoom_level
            self._canvas._needs_layout = True
            self._canvas._schedule_redraw()
        elif self._backend == "webkit_gtk" and hasattr(self, "webview"):
            self.webview.set_zoom_level(self._zoom_level)
        elif self._backend == "macos_webkit" and hasattr(self, "_macos_helper"):
            js = f"document.body.style.zoom = '{self._zoom_level}';"
            self._macos_helper._webview.evaluateJavaScript_completionHandler_(js, None)
        elif self._backend == "textview" and hasattr(self, "text_view"):
            base_size = 14
            scaled = int(base_size * self._zoom_level * Pango.SCALE)
            font_desc = Pango.FontDescription()
            font_desc.set_size(scaled)
            self.text_view.override_font(font_desc)

    def render(self, content: str, file_path: str = None):
        """Parse and render OpenAPI spec content."""
        self._last_content = content
        self._last_file_path = file_path
        spec = _parse_spec(content)
        base_dir = os.path.dirname(file_path) if file_path else None
        spec = _resolve_external_refs(spec, base_dir)

        if self._backend == "canvas":
            from editor.preview.openapi_block_renderer import OpenAPIBlockRenderer

            renderer = OpenAPIBlockRenderer()
            blocks = renderer.render(spec)
            self._canvas.set_blocks(blocks)
            return

        if self._backend in ("webkit_gtk", "macos_webkit"):
            theme = get_theme()
            css = _build_openapi_css(theme)
            body = _render_spec_html(spec)
            full_html = _HTML_TEMPLATE.format(css=css, body=body)
            # Inject scroll sync JS before closing </body>
            full_html = full_html.replace("</body>", f"{SCROLL_SYNC_JS}</body>")

            if self._backend == "webkit_gtk":
                self.webview.load_html(full_html, None)
            elif self._macos_attached:
                self._macos_helper.load_html(full_html)
                if self._target_fraction > 0.001:
                    GLib.timeout_add(300, self._apply_scroll_fraction)
            else:
                self._pending_html = full_html
        else:
            text = _render_spec_text(spec)
            self.buffer.set_text(text)
            if self._target_fraction > 0.001:
                GLib.idle_add(self._apply_scroll_fraction)

    def _on_theme_change(self, theme):
        """Update preview styles when theme changes."""
        if self._backend == "canvas" and hasattr(self, "_canvas"):
            self._apply_canvas_theme(theme)
            if self._last_content is not None:
                GLib.idle_add(lambda: self.render(self._last_content, self._last_file_path) or False)
            return
        if self._css_provider:
            if self._backend == "webkit_gtk":
                self._css_provider.load_from_data(f"webview {{ background-color: {theme.main_bg}; }}".encode())
            elif self._backend == "textview" and hasattr(self, "text_view"):
                css = f"""
                    textview text {{
                        background-color: {theme.main_bg};
                        color: {theme.fg_color};
                    }}
                """
                self._css_provider.load_from_data(css.encode())
        if self._last_content is not None:
            GLib.idle_add(lambda: self.render(self._last_content, self._last_file_path) or False)

    def _on_font_change(self, component, settings):
        """Re-render preview when markdown_preview or editor font changes."""
        if component in ("markdown_preview", "editor"):
            if self._backend == "canvas" and hasattr(self, "_canvas") and component == "markdown_preview":
                font_family = settings["family"]
                font_size = settings.get("size", 14)
                self._canvas.set_font(font_family, font_size)
            if self._last_content is not None:
                GLib.idle_add(lambda: self.render(self._last_content, self._last_file_path) or False)

    def update_from_editor(self, content: str, file_path: str = None):
        """Update preview from editor content (for live preview)."""
        self.render(content, file_path)
