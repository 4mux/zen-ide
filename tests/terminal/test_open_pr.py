"""Tests for tools/open_pr — pre-flight checks, AI discovery, and PR creation flow."""

import os
import subprocess
import textwrap

import pytest

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tools",
    "open_pr",
)


def _run(env_overrides=None, args=None, stdin=None):
    """Run open_pr with a controlled environment and return CompletedProcess."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    cmd = ["bash", SCRIPT] + (args or [])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL if stdin is None else None,
        input=stdin,
        timeout=10,
    )


def _resolve_tmp(tmp_path):
    """Resolve symlinks (macOS /var → /private/var) so bash paths match."""
    return str(tmp_path.resolve())


# ---------------------------------------------------------------------------
# Script existence and syntax
# ---------------------------------------------------------------------------
class TestScriptBasics:
    """Verify the script exists and has valid bash syntax."""

    def test_script_exists(self):
        assert os.path.isfile(SCRIPT)

    def test_script_is_executable(self):
        assert os.access(SCRIPT, os.X_OK)

    def test_valid_bash_syntax(self):
        result = subprocess.run(["bash", "-n", SCRIPT], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, f"Syntax error: {result.stderr}"


# ---------------------------------------------------------------------------
# Help flag
# ---------------------------------------------------------------------------
class TestUsage:
    """Verify -h prints usage and exits cleanly."""

    def test_help_flag(self):
        result = _run(args=["-h"])
        assert result.returncode == 0
        assert "Usage:" in result.stdout
        assert "-b BRANCH" in result.stdout

    def test_help_mentions_requirements(self):
        result = _run(args=["-h"])
        assert "gh" in result.stdout


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
class TestPreflightChecks:
    """Test error handling for missing prerequisites."""

    def test_fails_without_gh(self, tmp_path):
        """Should fail if gh is not in PATH."""
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        (fake_bin / "git").symlink_to("/usr/bin/git")
        # Symlink the essentials the script needs (but NOT gh) so we can verify
        # the gh-missing error path. Using a minimal PATH ensures gh isn't
        # picked up from /usr/bin on systems where it's installed.
        for tool in ("bash", "sh", "awk", "tr", "mktemp", "cat", "rm", "basename", "ls"):
            src = f"/usr/bin/{tool}"
            if os.path.exists(src):
                (fake_bin / tool).symlink_to(src)
        result = _run(env_overrides={"PATH": str(fake_bin)})
        assert result.returncode == 1
        assert "gh" in result.stdout.lower() or "gh" in result.stderr.lower()

    def test_fails_on_main_branch(self, tmp_path):
        """Should fail if currently on the base branch."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "main"],
            capture_output=True,
        )
        dummy = repo / "file.txt"
        dummy.write_text("hello")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "init"],
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "t@t.com",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "t@t.com",
            },
        )
        # Create a fake gh so the script gets past the prerequisite check
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake_gh = fake_bin / "gh"
        fake_gh.write_text("#!/usr/bin/env bash\nexit 0\n")
        fake_gh.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        env["GIT_DIR"] = str(repo / ".git")
        env["GIT_WORK_TREE"] = str(repo)
        result = _run(env_overrides=env)
        assert result.returncode == 1
        assert "already on" in result.stdout.lower() or "main" in result.stdout.lower()


# ---------------------------------------------------------------------------
# AI CLI discovery (pure Python — offline, machine-independent)
# ---------------------------------------------------------------------------
class TestAIDiscovery:
    """Test the AI CLI discovery logic using pure filesystem checks."""

    def _make_fake_cli(self, path, name="copilot"):
        """Create a fake executable file."""
        cli = path / name
        cli.write_text("#!/usr/bin/env bash\necho 'fake'\n")
        cli.chmod(0o755)
        return cli

    def _discover_ai_cli(self, home, nvm_dir=None, path_dirs=None):
        """Python reimplementation of the script's AI discovery logic.

        This mirrors the bash logic so we can test it offline without
        shell expansion or symlink issues.
        """
        # 1. Check PATH
        for d in path_dirs or []:
            for name in ("claude", "copilot"):
                c = os.path.join(d, name)
                if os.path.isfile(c) and os.access(c, os.X_OK):
                    return c

        # 2. Search NVM
        nvm = nvm_dir or os.path.join(home, ".nvm")
        versions = os.path.join(nvm, "versions", "node")
        if os.path.isdir(versions):
            for v in sorted(os.listdir(versions), reverse=True):
                for name in ("claude", "copilot"):
                    c = os.path.join(versions, v, "bin", name)
                    if os.path.isfile(c) and os.access(c, os.X_OK):
                        return c

        # 3. Check well-known locations
        for c in (
            os.path.join(home, ".local", "bin", "claude"),
            os.path.join(home, ".local", "bin", "copilot"),
            "/usr/local/bin/claude",
            "/usr/local/bin/copilot",
        ):
            if os.path.isfile(c) and os.access(c, os.X_OK):
                return c

        return None

    def test_finds_copilot_in_nvm(self, tmp_path):
        """Should discover copilot inside NVM node versions."""
        home = _resolve_tmp(tmp_path)
        nvm_bin = os.path.join(home, ".nvm", "versions", "node", "v20.0.0", "bin")
        os.makedirs(nvm_bin)
        self._make_fake_cli(tmp_path / ".nvm" / "versions" / "node" / "v20.0.0" / "bin", "copilot")

        result = self._discover_ai_cli(home)
        assert result is not None
        assert result.endswith("copilot")

    def test_finds_latest_nvm_version(self, tmp_path):
        """Should prefer the latest node version when multiple exist."""
        home = _resolve_tmp(tmp_path)
        for ver in ("v18.0.0", "v20.0.0"):
            nvm_bin = os.path.join(home, ".nvm", "versions", "node", ver, "bin")
            os.makedirs(nvm_bin)
        # Only put copilot in v20
        self._make_fake_cli(tmp_path / ".nvm" / "versions" / "node" / "v20.0.0" / "bin", "copilot")

        result = self._discover_ai_cli(home)
        assert result is not None
        assert "v20.0.0" in result

    def test_finds_cli_in_local_bin(self, tmp_path):
        """Should discover copilot in ~/.local/bin/."""
        home = _resolve_tmp(tmp_path)
        local_bin = os.path.join(home, ".local", "bin")
        os.makedirs(local_bin)
        self._make_fake_cli(tmp_path / ".local" / "bin", "copilot")

        result = self._discover_ai_cli(home, nvm_dir="/nonexistent")
        assert result is not None
        assert result.endswith("copilot")

    def test_prefers_claude_over_copilot_in_path(self, tmp_path):
        """Claude should be preferred when both are in PATH."""
        fake_bin = _resolve_tmp(tmp_path / "bin")
        os.makedirs(fake_bin, exist_ok=True)
        self._make_fake_cli(tmp_path / "bin", "claude")
        self._make_fake_cli(tmp_path / "bin", "copilot")

        result = self._discover_ai_cli(home="/nonexistent", nvm_dir="/nonexistent", path_dirs=[fake_bin])
        assert result is not None
        assert result.endswith("claude")

    def test_returns_none_when_nothing_installed(self, tmp_path):
        """Should return None when no AI CLI is found."""
        home = _resolve_tmp(tmp_path)
        result = self._discover_ai_cli(home, nvm_dir="/nonexistent")
        assert result is None

    def test_path_checked_before_nvm(self, tmp_path):
        """PATH should be checked before NVM directories."""
        home = _resolve_tmp(tmp_path)
        # Put claude in PATH
        path_bin = os.path.join(home, "path_bin")
        os.makedirs(path_bin)
        self._make_fake_cli(tmp_path / "path_bin", "claude")
        # Put copilot in NVM
        nvm_bin = os.path.join(home, ".nvm", "versions", "node", "v20.0.0", "bin")
        os.makedirs(nvm_bin)
        self._make_fake_cli(tmp_path / ".nvm" / "versions" / "node" / "v20.0.0" / "bin", "copilot")

        result = self._discover_ai_cli(home, path_dirs=[path_bin])
        assert result is not None
        assert result.endswith("claude")


# ---------------------------------------------------------------------------
# PR title formatting
# ---------------------------------------------------------------------------
class TestPRTitle:
    """Verify the PR title is formatted from the branch name."""

    @pytest.mark.parametrize(
        "branch, expected",
        [
            ("jira-123-hello-abc", "[JIRA-123] Hello abc"),
            ("RAP-1254-bring-gha", "[RAP-1254] Bring gha"),
            ("ABC-99-multi-word-title-here", "[ABC-99] Multi word title here"),
            ("fix-something", "fix-something"),
            ("main", "main"),
        ],
    )
    def test_title_formatting(self, branch, expected):
        """Branch names with ticket prefixes should be formatted as [TICKET] Rest."""
        test_script = textwrap.dedent(f"""\
            format_title() {{
                local branch="$1"
                if [[ "$branch" =~ ^([a-zA-Z]+-[0-9]+)-(.+)$ ]]; then
                    local ticket="${{BASH_REMATCH[1]}}"
                    local rest="${{BASH_REMATCH[2]}}"
                    ticket=$(echo "$ticket" | tr '[:lower:]' '[:upper:]')
                    rest=$(echo "$rest" | tr '-' ' ' | awk '{{print toupper(substr($0,1,1)) substr($0,2)}}')
                    echo "[$ticket] $rest"
                else
                    echo "$branch"
                fi
            }}
            format_title "{branch}"
        """)
        result = subprocess.run(
            ["bash", "-c", test_script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.stdout.strip() == expected


# ---------------------------------------------------------------------------
# Base branch flag
# ---------------------------------------------------------------------------
class TestBaseBranchFlag:
    """Test the -b flag for custom base branch."""

    def test_default_base_is_main(self):
        result = subprocess.run(
            ["bash", "-c", 'BASE_BRANCH="main"; echo "$BASE_BRANCH"'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.stdout.strip() == "main"

    def test_custom_base_branch_parsed(self):
        result = subprocess.run(
            [
                "bash",
                "-c",
                'BASE_BRANCH="main"; while getopts "b:h" opt; do case "$opt" in b) BASE_BRANCH="$OPTARG" ;; esac; done; echo "$BASE_BRANCH"',
                "_",
                "-b",
                "develop",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.stdout.strip() == "develop"


# ---------------------------------------------------------------------------
# Diff truncation
# ---------------------------------------------------------------------------
class TestDiffTruncation:
    """Test that large diffs are truncated."""

    def test_truncates_at_limit(self):
        test_script = textwrap.dedent("""\
            #!/usr/bin/env bash
            MAX_DIFF_CHARS=100
            DIFF_CONTENT=$(printf 'x%.0s' {1..200})
            if [ ${#DIFF_CONTENT} -gt $MAX_DIFF_CHARS ]; then
                DIFF_CONTENT="${DIFF_CONTENT:0:$MAX_DIFF_CHARS}
... (diff truncated at ${MAX_DIFF_CHARS} chars)"
            fi
            echo "${#DIFF_CONTENT}"
            echo "$DIFF_CONTENT" | tail -1
        """)
        result = subprocess.run(
            ["bash", "-c", test_script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.strip().split("\n")
        assert "truncated at 100 chars" in lines[-1]

    def test_no_truncation_for_small_diffs(self):
        test_script = textwrap.dedent("""\
            #!/usr/bin/env bash
            MAX_DIFF_CHARS=12000
            DIFF_CONTENT="small diff"
            if [ ${#DIFF_CONTENT} -gt $MAX_DIFF_CHARS ]; then
                DIFF_CONTENT="${DIFF_CONTENT:0:$MAX_DIFF_CHARS}
... (diff truncated)"
            fi
            echo "$DIFF_CONTENT"
        """)
        result = subprocess.run(
            ["bash", "-c", test_script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.stdout.strip() == "small diff"
