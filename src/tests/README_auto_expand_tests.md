# Auto Expand Terminals Regression Tests

This directory contains comprehensive regression tests for the `auto_expand_terminals` behavior fix.

## 🎯 What Was Fixed

The `auto_expand_terminals: false` setting was being ignored in multiple places in the codebase. When users set this setting to `false`, they expected terminals and AI chat to **stay where they are** when the editor has no tabs open, rather than expanding to fill the entire window space.

## 🔧 Code Changes Made

The following files were modified to respect the `auto_expand_terminals` setting:

1. **`main/window_events.py`**
   - `_expand_editor()` method - Now only calls terminal expansion when setting is enabled
   - `_on_tabs_empty()` method - Now only collapses editor when setting is enabled

2. **`main/window_panels.py`**
   - `_show_all_panels()` method - Now only collapses editor when no tabs if setting is enabled
   - `_apply_default_layout()` method - Now only resets terminal layout when setting is enabled  
   - `_restore_saved_positions()` method - Now only restores terminal positions when setting is enabled

3. **`main/window_state.py`**
   - `_reapply_saved_positions()` method - Now only restores saved positions when setting is enabled
   - `_create_bottom_panels()` method - Now only sets position when setting is enabled

## 📁 Test Files

### `test_auto_expand_simple.py`
- **Purpose**: Automated unit tests for core logic
- **Coverage**: Settings storage/retrieval, conditional logic, user scenarios
- **Run**: `python3 test_auto_expand_simple.py`

### `manual_test_auto_expand.py`
- **Purpose**: Manual verification script for developers and users
- **Coverage**: Real setting operations, code location documentation, step-by-step verification
- **Run**: `python3 manual_test_auto_expand.py`

### `run_all_auto_expand_tests.py`
- **Purpose**: Comprehensive test runner that runs both automated and manual tests
- **Coverage**: Complete regression test suite with detailed reporting
- **Run**: `python3 run_all_auto_expand_tests.py`

## 🏃‍♂️ How to Run Tests

### Run All Tests (Recommended)
```bash
cd tests
python3 run_all_auto_expand_tests.py
```

### Run Only Automated Tests
```bash
cd tests
python3 run_all_auto_expand_tests.py --automated-only
# OR
python3 test_auto_expand_simple.py
```

### Run Only Manual Verification
```bash
cd tests
python3 run_all_auto_expand_tests.py --manual-only
# OR  
python3 manual_test_auto_expand.py
```

## ✅ Expected Test Results

When all tests pass, you should see:

```
🎉 ALL REGRESSION TESTS PASSED!
✅ The auto_expand_terminals fix is working correctly and has comprehensive test coverage.

🔒 REGRESSION PROTECTION:
   - Settings system is working properly
   - All 7 code paths respect the auto_expand_terminals setting
   - Both True and False behaviors are preserved
   - Edge cases are handled correctly

🚀 READY FOR DEPLOYMENT!
```

## 📋 What These Tests Verify

### Settings System
- ✅ `auto_expand_terminals` can be set to `false` and `true`
- ✅ Setting values persist across multiple reads
- ✅ Setting changes take effect immediately
- ✅ Default values are respected when setting doesn't exist

### Code Logic
- ✅ Conditional logic correctly branches based on setting value
- ✅ All 7 fixed code paths respect the setting
- ✅ Original behavior preserved when `auto_expand_terminals: true`
- ✅ New behavior works when `auto_expand_terminals: false`

### User Scenarios
- ✅ When setting is `false`: Terminals/AI chat stay in current positions when editor has no tabs
- ✅ When setting is `true`: Original auto-expansion behavior is preserved
- ✅ Multiple setting changes work correctly
- ✅ Edge cases don't cause crashes

### Regression Protection
- ✅ All previously broken code paths now work correctly
- ✅ No existing functionality was broken by the fixes
- ✅ Future changes won't accidentally break the fix (tests will catch it)

## 🔍 Manual Verification Steps

After running the tests, you can manually verify the fix works in the actual IDE:

1. Set `"auto_expand_terminals": false` in your Zen IDE settings
2. Restart Zen IDE
3. Arrange your terminals/AI chat in specific positions
4. Close all open file tabs (editor becomes empty)
5. **Expected**: Terminals/AI chat should stay in their current positions (NOT expand to fill window)
6. Open a new file
7. **Expected**: Editor expands, but terminals/AI chat remain in their previous positions

## 🛡️ Regression Prevention

These tests serve as a safety net to ensure that:

- The `auto_expand_terminals` setting continues to work correctly
- Future code changes don't accidentally break the fix
- All edge cases continue to be handled properly
- The settings system remains reliable

Run these tests after any changes to window layout, panel management, or settings-related code to ensure the fix remains working.

## 🤝 Contributing

When modifying code that affects window layout or terminal/panel positioning:

1. Run the regression tests: `python3 run_all_auto_expand_tests.py`
2. Ensure all tests pass
3. If you modify any of the fixed methods, add additional test cases if needed
4. Manual testing is also recommended for GUI-related changes

## 📞 Troubleshooting

### Tests Fail
- Check that you're running from the `tests` directory
- Ensure Python 3 is being used
- Verify that the `shared.settings` module is working correctly
- Check that no import errors occur

### Setting Doesn't Work in IDE
- Restart the IDE after changing the setting
- Clear browser cache if using web version
- Verify setting is stored correctly by running the manual test
- Check that you're using the correct setting key: `"behavior.auto_expand_terminals"`

---

*These regression tests ensure that the embarrassing auto-expand issue is fixed once and for all! 🎉*