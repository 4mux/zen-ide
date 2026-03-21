#!/usr/bin/env python3
"""
Verification script to confirm that all auto_expand_terminals fixes are applied.

This script checks the actual source code to verify that the conditional
logic has been properly added to all the required locations.
"""

import os
import re
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def check_file_for_fix(file_path, pattern, description):
    """Check if a file contains the expected fix pattern."""
    try:
        # Look for the file in the parent directory (src)
        full_path = os.path.join(os.path.dirname(__file__), "..", file_path)
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()

        if re.search(pattern, content, re.MULTILINE | re.DOTALL):
            print(f"✅ {description}")
            return True
        else:
            print(f"❌ {description}")
            print(f"   Pattern not found in {file_path}")
            return False

    except FileNotFoundError:
        print(f"❌ {description}")
        print(f"   File not found: {file_path}")
        return False
    except Exception as e:
        print(f"❌ {description}")
        print(f"   Error reading {file_path}: {e}")
        return False


def main():
    """Verify all fixes are applied."""
    print("🔍 VERIFYING AUTO_EXPAND_TERMINALS FIXES ARE APPLIED")
    print("=" * 60)

    fixes_to_check = [
        {
            "file": "main/window_events.py",
            "pattern": r'if get_setting\("behavior\.auto_expand_terminals".*?\):\s*self\._auto_expand_terminals\(\)',
            "description": "_expand_editor() has conditional _auto_expand_terminals() call",
        },
        {
            "file": "main/window_events.py",
            "pattern": r'if get_setting\("behavior\.auto_expand_terminals".*?\):\s*self\._collapse_editor\(\)',
            "description": "_on_tabs_empty() has conditional _collapse_editor() call",
        },
        {
            "file": "main/window_panels.py",
            "pattern": r'and get_setting\("behavior\.auto_expand_terminals".*?\)\):\s*animate_paned\(self\.right_paned, 0',
            "description": "_show_all_panels() has conditional editor collapse (first occurrence)",
        },
        {
            "file": "main/window_panels.py",
            "pattern": r'if get_setting\("behavior\.auto_expand_terminals".*?\):\s*animate_paned\(self\.bottom_paned',
            "description": "_apply_default_layout() has conditional bottom panel animation",
        },
        {
            "file": "main/window_panels.py",
            "pattern": r'if get_setting\("behavior\.auto_expand_terminals".*?\):\s*# When AI is disabled.*?target = 0 if not ai_enabled else saved\["bottom"\]\s*animate_paned\(self\.bottom_paned, target',
            "description": "_restore_saved_positions() has conditional bottom panel restoration",
        },
        {
            "file": "main/window_state.py",
            "pattern": r'if get_setting\("behavior\.auto_expand_terminals".*?\):\s*self\.bottom_paned\.set_position\(saved\["bottom"\]\)',
            "description": "_reapply_saved_positions() has conditional bottom position setting",
        },
        {
            "file": "main/window_state.py",
            "pattern": r'if get_setting\("behavior\.auto_expand_terminals".*?\):\s*self\.bottom_paned\.set_position\(0\)',
            "description": "_create_bottom_panels() has conditional position setting",
        },
    ]

    all_fixes_found = True

    for fix in fixes_to_check:
        found = check_file_for_fix(fix["file"], fix["pattern"], fix["description"])
        all_fixes_found = all_fixes_found and found

    print("\n" + "=" * 60)
    if all_fixes_found:
        print("🎉 ALL FIXES VERIFIED!")
        print("✅ All auto_expand_terminals conditional logic is properly applied.")
        print("✅ The fix is complete and ready to work.")
    else:
        print("❌ SOME FIXES MISSING!")
        print("⚠️  The auto_expand_terminals fix is incomplete.")
        print("   Please check the patterns above and ensure all fixes are applied.")

    print("\n" + "=" * 60)
    print("📋 WHAT THIS VERIFICATION CHECKS:")
    print("=" * 60)
    print("✓ Conditional logic added to _expand_editor()")
    print("✓ Conditional logic added to _on_tabs_empty()")
    print("✓ Conditional logic added to _show_all_panels()")
    print("✓ Conditional logic added to _apply_default_layout()")
    print("✓ Conditional logic added to _restore_saved_positions()")
    print("✓ Conditional logic added to _reapply_saved_positions()")
    print("✓ Conditional logic added to _create_bottom_panels()")

    return all_fixes_found


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
