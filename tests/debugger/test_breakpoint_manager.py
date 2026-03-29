"""Tests for debugger/breakpoint_manager.py — breakpoint state and persistence."""

import os
import tempfile
from unittest.mock import patch

from debugger.breakpoint_manager import (
    Breakpoint,
    BreakpointManager,
    BreakpointType,
)


def _make_manager():
    """Create a fresh BreakpointManager without loading from disk."""
    with patch.object(BreakpointManager, "load"):
        mgr = BreakpointManager()
    return mgr


class TestToggle:
    """Test toggle behavior."""

    def test_toggle_adds_breakpoint(self):
        mgr = _make_manager()
        result = mgr.toggle("/test.py", 10)
        assert result is True
        assert len(mgr.get_for_file("/test.py")) == 1

    def test_toggle_removes_existing(self):
        mgr = _make_manager()
        mgr.toggle("/test.py", 10)
        result = mgr.toggle("/test.py", 10)
        assert result is False
        assert len(mgr.get_for_file("/test.py")) == 0

    def test_toggle_different_lines(self):
        mgr = _make_manager()
        mgr.toggle("/test.py", 10)
        mgr.toggle("/test.py", 20)
        assert len(mgr.get_for_file("/test.py")) == 2


class TestAddRemove:
    """Test add/remove operations."""

    def test_add_creates_breakpoint(self):
        mgr = _make_manager()
        bp = mgr.add("/test.py", 10)
        assert isinstance(bp, Breakpoint)
        assert bp.file_path == "/test.py"
        assert bp.line == 10
        assert bp.enabled is True
        assert bp.bp_type == BreakpointType.LINE

    def test_add_conditional(self):
        mgr = _make_manager()
        bp = mgr.add("/test.py", 10, condition="x > 5")
        assert bp.condition == "x > 5"
        assert bp.bp_type == BreakpointType.CONDITIONAL
        assert bp.is_conditional is True

    def test_add_logpoint(self):
        mgr = _make_manager()
        bp = mgr.add("/test.py", 10, log_message="Value: {x}")
        assert bp.log_message == "Value: {x}"
        assert bp.bp_type == BreakpointType.LOGPOINT
        assert bp.is_logpoint is True

    def test_add_duplicate_returns_existing(self):
        mgr = _make_manager()
        bp1 = mgr.add("/test.py", 10)
        bp2 = mgr.add("/test.py", 10)
        assert bp1 is bp2

    def test_remove(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10)
        mgr.remove("/test.py", 10)
        assert len(mgr.get_for_file("/test.py")) == 0

    def test_remove_nonexistent_is_safe(self):
        mgr = _make_manager()
        mgr.remove("/test.py", 10)  # Should not raise

    def test_remove_cleans_empty_file(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10)
        mgr.remove("/test.py", 10)
        assert "/test.py" not in mgr._breakpoints


class TestEnabledDisabled:
    """Test enable/disable operations."""

    def test_set_enabled_false(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10)
        mgr.set_enabled("/test.py", 10, False)
        bp = mgr.get_for_file("/test.py")[0]
        assert bp.enabled is False

    def test_set_enabled_true(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10)
        mgr.set_enabled("/test.py", 10, False)
        mgr.set_enabled("/test.py", 10, True)
        bp = mgr.get_for_file("/test.py")[0]
        assert bp.enabled is True

    def test_get_enabled_lines(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10)
        mgr.add("/test.py", 20)
        mgr.set_enabled("/test.py", 20, False)
        lines = mgr.get_enabled_lines("/test.py")
        assert lines == [10]

    def test_get_enabled_conditions(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10, condition="x > 5")
        mgr.add("/test.py", 20)
        conditions = mgr.get_enabled_conditions("/test.py")
        assert conditions == ["x > 5", ""]


class TestConditionsAndLogpoints:
    """Test condition and logpoint management."""

    def test_set_condition(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10)
        mgr.set_condition("/test.py", 10, "x > 5")
        bp = mgr.get_for_file("/test.py")[0]
        assert bp.condition == "x > 5"
        assert bp.bp_type == BreakpointType.CONDITIONAL

    def test_clear_condition(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10, condition="x > 5")
        mgr.set_condition("/test.py", 10, "")
        bp = mgr.get_for_file("/test.py")[0]
        assert bp.condition == ""
        assert bp.bp_type == BreakpointType.LINE

    def test_set_log_message(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10)
        mgr.set_log_message("/test.py", 10, "Value: {x}")
        bp = mgr.get_for_file("/test.py")[0]
        assert bp.log_message == "Value: {x}"
        assert bp.bp_type == BreakpointType.LOGPOINT


class TestClear:
    """Test clear operations."""

    def test_clear_file(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10)
        mgr.add("/test.py", 20)
        mgr.clear_file("/test.py")
        assert len(mgr.get_for_file("/test.py")) == 0

    def test_clear_all(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10)
        mgr.add("/lib.py", 5)
        mgr.clear_all()
        assert mgr.get_all() == {}


class TestGetters:
    """Test getter methods."""

    def test_get_for_file_returns_copy(self):
        mgr = _make_manager()
        mgr.add("/test.py", 10)
        bps = mgr.get_for_file("/test.py")
        bps.clear()  # Mutating the returned list should not affect internal state
        assert len(mgr.get_for_file("/test.py")) == 1

    def test_get_all(self):
        mgr = _make_manager()
        mgr.add("/a.py", 1)
        mgr.add("/b.py", 2)
        all_bps = mgr.get_all()
        assert "/a.py" in all_bps
        assert "/b.py" in all_bps

    def test_has_breakpoints(self):
        mgr = _make_manager()
        assert mgr.has_breakpoints("/test.py") is False
        mgr.add("/test.py", 10)
        assert mgr.has_breakpoints("/test.py") is True


class TestSubscription:
    """Test change notification subscription."""

    def test_subscribe_notified_on_add(self):
        mgr = _make_manager()
        notifications = []
        mgr.subscribe(lambda f, a: notifications.append((f, a)))
        mgr.add("/test.py", 10)
        assert len(notifications) == 1
        assert notifications[0] == ("/test.py", "added")

    def test_subscribe_notified_on_remove(self):
        mgr = _make_manager()
        notifications = []
        mgr.subscribe(lambda f, a: notifications.append((f, a)))
        mgr.add("/test.py", 10)
        mgr.remove("/test.py", 10)
        assert any(n[1] == "removed" for n in notifications)

    def test_subscribe_notified_on_change(self):
        mgr = _make_manager()
        notifications = []
        mgr.subscribe(lambda f, a: notifications.append((f, a)))
        mgr.add("/test.py", 10)
        mgr.set_enabled("/test.py", 10, False)
        assert any(n[1] == "changed" for n in notifications)

    def test_unsubscribe(self):
        mgr = _make_manager()
        notifications = []
        cb = lambda f, a: notifications.append((f, a))
        mgr.subscribe(cb)
        mgr.unsubscribe(cb)
        mgr.add("/test.py", 10)
        assert len(notifications) == 0

    def test_subscriber_exception_doesnt_propagate(self):
        mgr = _make_manager()

        def bad_callback(f, a):
            raise RuntimeError("boom")

        mgr.subscribe(bad_callback)
        mgr.add("/test.py", 10)  # Should not raise


class TestExceptionBreakpoints:
    """Test exception breakpoint filters."""

    def test_set_and_get_exception_filters(self):
        mgr = _make_manager()
        mgr.set_exception_filters(["uncaught", "raised"])
        assert mgr.get_exception_filters() == ["uncaught", "raised"]

    def test_empty_filters(self):
        mgr = _make_manager()
        assert mgr.get_exception_filters() == []


class TestFunctionBreakpoints:
    """Test function breakpoints."""

    def test_add_function_breakpoint(self):
        mgr = _make_manager()
        mgr.add_function_breakpoint("main")
        assert "main" in mgr.get_function_breakpoints()

    def test_add_duplicate_function_breakpoint(self):
        mgr = _make_manager()
        mgr.add_function_breakpoint("main")
        mgr.add_function_breakpoint("main")
        assert mgr.get_function_breakpoints().count("main") == 1

    def test_remove_function_breakpoint(self):
        mgr = _make_manager()
        mgr.add_function_breakpoint("main")
        mgr.remove_function_breakpoint("main")
        assert "main" not in mgr.get_function_breakpoints()


class TestPersistence:
    """Test save/load to disk."""

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bp_file = os.path.join(tmpdir, "breakpoints.json")
            # Create real files so load() doesn't prune them
            test_py = os.path.join(tmpdir, "test.py")
            lib_py = os.path.join(tmpdir, "lib.py")
            open(test_py, "w").close()
            open(lib_py, "w").close()

            with (
                patch("debugger.breakpoint_manager._BREAKPOINTS_FILE", bp_file),
                patch("debugger.breakpoint_manager.SETTINGS_DIR", tmpdir),
            ):
                mgr = _make_manager()
                mgr.add(test_py, 10, condition="x > 5")
                mgr.add(test_py, 20)
                mgr.set_enabled(test_py, 20, False)
                mgr.add(lib_py, 5, log_message="Debug: {val}")
                mgr.set_exception_filters(["uncaught"])
                mgr.add_function_breakpoint("main")
                mgr.save()

                # Create a new manager and load
                mgr2 = _make_manager()
                mgr2.load()

                bps_test = mgr2.get_for_file(test_py)
                assert len(bps_test) == 2
                assert bps_test[0].condition == "x > 5"
                assert bps_test[1].enabled is False

                bps_lib = mgr2.get_for_file(lib_py)
                assert len(bps_lib) == 1
                assert bps_lib[0].log_message == "Debug: {val}"

                assert mgr2.get_exception_filters() == ["uncaught"]
                assert mgr2.get_function_breakpoints() == ["main"]

    def test_load_prunes_deleted_files(self):
        """Breakpoints for files that no longer exist are removed on load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bp_file = os.path.join(tmpdir, "breakpoints.json")
            real_file = os.path.join(tmpdir, "real.py")
            open(real_file, "w").close()

            with (
                patch("debugger.breakpoint_manager._BREAKPOINTS_FILE", bp_file),
                patch("debugger.breakpoint_manager.SETTINGS_DIR", tmpdir),
            ):
                mgr = _make_manager()
                mgr.add(real_file, 10)
                mgr.add("/nonexistent/ghost.py", 5)
                mgr.save()

                mgr2 = _make_manager()
                mgr2.load()

                assert len(mgr2.get_for_file(real_file)) == 1
                assert len(mgr2.get_for_file("/nonexistent/ghost.py")) == 0

    def test_load_missing_file_is_safe(self):
        with patch("debugger.breakpoint_manager._BREAKPOINTS_FILE", "/nonexistent/path.json"):
            mgr = _make_manager()
            mgr.load()  # Should not raise

    def test_load_corrupt_file_is_safe(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json {{{")
            f.flush()
            try:
                with patch("debugger.breakpoint_manager._BREAKPOINTS_FILE", f.name):
                    mgr = _make_manager()
                    mgr.load()  # Should not raise
            finally:
                os.unlink(f.name)
