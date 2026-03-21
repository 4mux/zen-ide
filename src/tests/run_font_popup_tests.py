#!/usr/bin/env python3
"""
Test runner for font popup closing behavior regression tests.

This script runs all the font popup fix tests and provides
a comprehensive report of what was tested and the results.
"""

import os
import sys
import unittest
from io import StringIO

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def run_font_popup_tests():
    """Run all font popup fix regression tests."""

    print("=" * 80)
    print("FONT POPUP CLOSING BEHAVIOR REGRESSION TEST SUITE")
    print("=" * 80)
    print()

    # Import the test module
    try:
        from test_font_popup_fix import (
            TestDocumentationAndStructure,
            TestFontPopupClosingBehavior,
            TestFontPopupMethodBehavior,
            TestRegressionProtection,
        )

        print("✅ Successfully imported test modules")
    except ImportError as e:
        print(f"❌ Failed to import test modules: {e}")
        return False

    # Create test suite
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestFontPopupClosingBehavior))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestFontPopupMethodBehavior))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestDocumentationAndStructure))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestRegressionProtection))

    # Run tests with detailed output
    stream = StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2, descriptions=True, failfast=False)

    print("Running regression tests...")
    print()

    result = runner.run(suite)

    # Print the test output
    test_output = stream.getvalue()
    print(test_output)

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
    print("WHAT THESE TESTS VERIFY:")
    print("=" * 80)
    print("✓ Font picker dialog doesn't close when 'Apply to' button is clicked")
    print("✓ All automatic closing mechanisms are properly disabled:")
    print("  - _on_focus_leave() override prevents focus-based closing")
    print("  - _on_active_changed() override prevents active-state-based closing")
    print("  - _check_active_and_close() override prevents delayed closing")
    print("✓ Context menu (combo box) properly connects to correct close signals:")
    print("  - NvimContextMenu uses 'close-request' signal")
    print("  - SystemContextMenu uses 'closed' signal")
    print("✓ Sub-popup state management works correctly:")
    print("  - _sub_popup is set when context menu opens")
    print("  - _sub_popup is not cleared prematurely when option is selected")
    print("  - _sub_popup is cleared after focus is restored when menu closes")
    print("✓ Manual closing methods still work properly:")
    print("  - Cancel button closes dialog and reverts changes")
    print("  - Apply button closes dialog and applies changes")
    print("  - Escape key closes dialog and reverts changes")
    print("✓ Focus restoration works correctly after context menu closes")
    print("✓ Complete workflow integration from button click to menu selection")

    return success


if __name__ == "__main__":
    success = run_font_popup_tests()
    sys.exit(0 if success else 1)
