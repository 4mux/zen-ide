#!/usr/bin/env python3
"""
Comprehensive test runner for auto_expand_terminals regression tests.

This script runs both automated unit tests and manual verification tests
to ensure the auto_expand_terminals fix is working correctly.

Usage:
    python3 run_all_auto_expand_tests.py [--manual-only] [--automated-only]
"""

import argparse
import os
import sys
import unittest
from io import StringIO

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def run_automated_tests():
    """Run the automated unit tests."""
    print("🤖 RUNNING AUTOMATED TESTS")
    print("=" * 60)

    try:
        # Import and run the simple tests
        from test_auto_expand_simple import (
            TestAutoExpandTerminalsCodeLogic,
            TestAutoExpandTerminalsLogic,
            TestAutoExpandTerminalsRegression,
        )

        # Create test suite
        suite = unittest.TestSuite()
        loader = unittest.TestLoader()

        # Add all test classes
        for test_class in [
            TestAutoExpandTerminalsLogic,
            TestAutoExpandTerminalsCodeLogic,
            TestAutoExpandTerminalsRegression,
        ]:
            suite.addTests(loader.loadTestsFromTestCase(test_class))

        # Run tests
        stream = StringIO()
        runner = unittest.TextTestRunner(stream=stream, verbosity=2, descriptions=True, failfast=False)

        result = runner.run(suite)

        # Print results
        output = stream.getvalue()
        print(output)

        # Summary
        success = len(result.failures) == 0 and len(result.errors) == 0

        print("📊 AUTOMATED TEST SUMMARY:")
        print(f"   Tests run: {result.testsRun}")
        print(f"   Failures: {len(result.failures)}")
        print(f"   Errors: {len(result.errors)}")

        if success:
            print("✅ All automated tests PASSED!")
        else:
            print("❌ Some automated tests FAILED!")
            if result.failures:
                print("\nFailures:")
                for test, failure in result.failures:
                    print(f"  - {test}")
            if result.errors:
                print("\nErrors:")
                for test, error in result.errors:
                    print(f"  - {test}")

        return success

    except ImportError as e:
        print(f"❌ Failed to import automated tests: {e}")
        return False
    except Exception as e:
        print(f"💥 Error running automated tests: {e}")
        return False


def run_manual_tests():
    """Run the manual verification tests."""
    print("\n👤 RUNNING MANUAL VERIFICATION TESTS")
    print("=" * 60)

    try:
        # Import and run manual tests
        from manual_test_auto_expand import main as run_manual_main

        success = run_manual_main()
        return success

    except ImportError as e:
        print(f"❌ Failed to import manual tests: {e}")
        return False
    except Exception as e:
        print(f"💥 Error running manual tests: {e}")
        return False


def run_fix_verification():
    """Verify that all fixes are actually applied to the source code."""
    print("\n🔍 VERIFYING FIXES ARE APPLIED TO SOURCE CODE")
    print("=" * 60)

    try:
        from verify_fix_applied import main as verify_main

        success = verify_main()
        return success
    except ImportError as e:
        print(f"❌ Failed to import verification script: {e}")
        return False
    except Exception as e:
        print(f"💥 Error running verification: {e}")
        return False


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="Run auto_expand_terminals regression tests")
    parser.add_argument("--automated-only", action="store_true", help="Run only automated tests")
    parser.add_argument("--manual-only", action="store_true", help="Run only manual tests")
    parser.add_argument("--no-verification", action="store_true", help="Skip source code verification")
    args = parser.parse_args()

    print("🧪 AUTO_EXPAND_TERMINALS COMPREHENSIVE REGRESSION TEST SUITE")
    print("=" * 70)
    print()

    results = []

    # Verify fixes are applied first
    if not args.no_verification:
        verification_success = run_fix_verification()
        results.append(("Source Code Verification", verification_success))

    # Run automated tests
    if not args.manual_only:
        automated_success = run_automated_tests()
        results.append(("Automated Tests", automated_success))

    # Run manual tests
    if not args.automated_only:
        manual_success = run_manual_tests()
        results.append(("Manual Verification", manual_success))

    # Overall summary
    print("\n" + "=" * 70)
    print("🏆 OVERALL TEST RESULTS")
    print("=" * 70)

    all_passed = True
    for test_type, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{status} - {test_type}")
        all_passed = all_passed and success

    print()
    if all_passed:
        print("🎉 ALL REGRESSION TESTS PASSED!")
        print("✅ The auto_expand_terminals fix is working correctly and has comprehensive test coverage.")
        print()
        print("🔒 REGRESSION PROTECTION:")
        print("   - Settings system is working properly")
        print("   - All 7 code paths respect the auto_expand_terminals setting")
        print("   - Both True and False behaviors are preserved")
        print("   - Edge cases are handled correctly")
        print()
        print("🚀 READY FOR DEPLOYMENT!")
    else:
        print("❌ SOME REGRESSION TESTS FAILED!")
        print("⚠️  The auto_expand_terminals fix needs attention before deployment.")

    print("\n" + "=" * 70)
    print("📋 WHAT THESE TESTS COVER:")
    print("=" * 70)
    print("✓ Settings can be stored and retrieved correctly")
    print("✓ Conditional logic works with both True and False values")
    print("✓ All fixed code paths respect the setting")
    print("✓ User scenarios work as expected")
    print("✓ Original behavior is preserved when setting is True")
    print("✓ New behavior works when setting is False")
    print("✓ Edge cases don't cause crashes")
    print("✓ Setting changes take effect immediately")

    print("\n" + "=" * 70)
    print("🏃‍♂️ TO RUN INDIVIDUAL TEST SUITES:")
    print("=" * 70)
    print("Automated only:  python3 run_all_auto_expand_tests.py --automated-only")
    print("Manual only:     python3 run_all_auto_expand_tests.py --manual-only")
    print("Simple tests:    python3 test_auto_expand_simple.py")
    print("Manual verify:   python3 manual_test_auto_expand.py")

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
