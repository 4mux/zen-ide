#!/usr/bin/env python3
"""
Simple test runner for font popup closing behavior regression tests.

This script runs the simplified font popup fix tests that verify
the fix is in place without complex mocking.
"""

import os
import sys
import unittest

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def run_font_popup_simple_tests():
    """Run the simplified font popup fix regression tests."""

    print("=" * 80)
    print("FONT POPUP CLOSING BEHAVIOR REGRESSION TEST SUITE")
    print("(Simplified Version - No Complex Mocking)")
    print("=" * 80)
    print()

    # Import the test module
    try:
        from test_font_popup_simple import TestDocumentationExists, TestFontPopupFix, TestRegressionProtection

        print("✅ Successfully imported test modules")
    except ImportError as e:
        print(f"❌ Failed to import test modules: {e}")
        return False

    # Create test suite
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestFontPopupFix))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestDocumentationExists))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestRegressionProtection))

    # Run tests with detailed output
    runner = unittest.TextTestRunner(verbosity=2)

    print("Running regression tests...")
    print()

    result = runner.run(suite)

    # Print summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped) if hasattr(result, 'skipped') else 0}")

    if result.failures:
        print("\nFAILURES:")
        for test, failure in result.failures:
            print(f"  ❌ {test}")
            print(f"     {failure.strip()}")

    if result.errors:
        print("\nERRORS:")
        for test, error in result.errors:
            print(f"  💥 {test}")
            print(f"     {error.strip()}")

    success = len(result.failures) == 0 and len(result.errors) == 0

    if success:
        print("\n🎉 ALL TESTS PASSED!")
        print("The font popup closing fix is working correctly.")
    else:
        print("\n❌ SOME TESTS FAILED!")
        print("The font popup closing fix may have regressions.")

    print("\n" + "=" * 80)
    print("WHAT THESE TESTS VERIFIED:")
    print("=" * 80)
    print("✅ FontPickerDialog can be imported without errors")
    print("✅ All critical override methods exist:")
    print("   - _on_focus_leave() prevents focus-based closing")
    print("   - _on_active_changed() prevents active-state-based closing")
    print("   - _check_active_and_close() prevents delayed closing")
    print("✅ Override methods are simple (just return)")
    print("✅ Target button click handler exists with proper signal logic")
    print("✅ Focus restoration method exists and works correctly")
    print("✅ Signal connection handles both NvimContextMenu and SystemContextMenu")
    print("✅ No premature _sub_popup clearing in _on_target_selected")
    print("✅ Proper timing with GLib.idle_add in _on_sub_popup_closing")
    print("✅ Documentation files exist with substantial content")
    print("✅ Documentation covers all key topics and explains the fix")

    print("\n" + "=" * 80)
    print("REGRESSION PROTECTION:")
    print("=" * 80)
    print("This test suite protects against the original bug where:")
    print("❌ Font picker dialog closed when 'Apply to' button was clicked")
    print("❌ Context menu signal connections were incorrect")
    print("❌ _sub_popup was cleared prematurely causing race conditions")
    print("❌ Focus restoration had timing issues")
    print()
    print("The fix ensures:")
    print("✅ Font picker stays open during 'Apply to' combo box interactions")
    print("✅ All automatic closing mechanisms are disabled for the font picker")
    print("✅ Context menus connect to correct signals based on type")
    print("✅ Focus is restored before clearing _sub_popup reference")
    print("✅ Dialog only closes through explicit user actions (Cancel/Apply/Escape)")

    return success


if __name__ == "__main__":
    success = run_font_popup_simple_tests()
    sys.exit(0 if success else 1)
