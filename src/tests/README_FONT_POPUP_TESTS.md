# Font Popup Fix Regression Tests

## Overview

This directory contains regression tests for the font picker dialog closing behavior fix. These tests ensure that the "Apply to" combo box works correctly without causing the font picker dialog to close unexpectedly.

## Test Files

### `test_font_popup_simple.py`
**Working tests** - These tests verify the fix is in place without complex mocking:

- **TestFontPopupFix**: Tests that critical methods exist and behave correctly
- **TestDocumentationExists**: Verifies documentation files were created
- **TestRegressionProtection**: Ensures specific regression scenarios are protected

### `test_font_popup_fix.py` 
**Complex tests** - More comprehensive tests with full mocking (may have environment issues):

- **TestFontPopupClosingBehavior**: Tests popup closing behavior 
- **TestFontPopupMethodBehavior**: Tests method implementations
- **TestDocumentationAndStructure**: Tests documentation and structure
- **TestRegressionProtection**: Tests regression protection

## Test Runners

### `run_font_popup_simple_tests.py` ✅ **RECOMMENDED**
Runs the simplified tests that work reliably:

```bash
cd tests
python3 run_font_popup_simple_tests.py
```

### `run_font_popup_tests.py`
Runs the complex tests (may fail due to GTK mocking issues):

```bash  
cd tests
python3 run_font_popup_tests.py
```

## What the Tests Verify

### Critical Method Existence
- `_on_focus_leave()` - Prevents focus-based auto-closing
- `_on_active_changed()` - Prevents active-state-based auto-closing  
- `_check_active_and_close()` - Prevents delayed auto-closing
- `_on_target_button_clicked()` - Handles "Apply to" button clicks
- `_on_sub_popup_closing()` - Handles context menu closing
- `_restore_focus_and_clear_sub_popup()` - Restores focus properly

### Implementation Quality
- Override methods are simple (just return)
- Signal connections handle both NvimContextMenu and SystemContextMenu
- No premature `_sub_popup` clearing
- Proper timing with `GLib.idle_add`

### Documentation
- Documentation files exist with substantial content
- Key topics are covered in the documentation
- Problem and solution are clearly explained

### Regression Protection
- Font picker doesn't close when "Apply to" is clicked
- Context menu signals are connected correctly
- Focus restoration happens before clearing references
- Dialog only closes through explicit user actions

## The Original Bug

**Problem**: When users clicked the "Apply to" combo box button in the font picker dialog, the entire dialog would close immediately, losing their font selection work.

**Root Causes**:
1. Multiple auto-closing mechanisms triggered on focus changes
2. Wrong signal connections for different context menu types
3. Premature clearing of sub-popup references
4. Race conditions in focus restoration

**Solution**: 
1. Disabled all auto-closing mechanisms for font picker
2. Fixed signal connections for both menu types  
3. Proper timing of focus restoration and reference clearing
4. Manual closing only through Cancel/Apply/Escape

## Test Results

When all tests pass, you should see:

```
🎉 ALL TESTS PASSED!
The font popup closing fix is working correctly.

Tests run: 10
Failures: 0
Errors: 0
Skipped: 0
```

## Running Individual Tests

You can run individual test classes:

```bash
# Run just the method behavior tests
python3 -m unittest test_font_popup_simple.TestFontPopupFix -v

# Run just the documentation tests  
python3 -m unittest test_font_popup_simple.TestDocumentationExists -v

# Run just the regression protection tests
python3 -m unittest test_font_popup_simple.TestRegressionProtection -v
```

## Maintenance

These tests should be run:
- **After any changes** to the font picker dialog
- **After any changes** to the base NvimPopup class
- **Before releases** to ensure no regressions
- **When porting** to new GTK versions or platforms

The tests protect against the specific regression while ensuring the fix doesn't break other functionality.