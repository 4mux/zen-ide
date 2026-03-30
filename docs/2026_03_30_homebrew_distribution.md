---
Created_at: 2026-03-30
Updated_at: 2026-03-30
Status: draft
Goal: Distribute Zen IDE via Homebrew to avoid macOS Gatekeeper warnings
Scope: Homebrew tap setup, formula, and release automation
---

# Homebrew Distribution

## Why

Apps downloaded from the internet carry a `com.apple.quarantine` extended attribute.
macOS Gatekeeper uses this to show the *"Apple could not verify…"* warning.
Homebrew strips this attribute automatically — **no code signing or notarization needed**.

This is how Neovim, ripgrep, fd, and most CLI/GUI developer tools avoid the warning.

## How It Works

```
User runs:  brew tap YOUR_USER/zen-ide && brew install zen-ide
                          ↓
Homebrew downloads source tarball from GitHub Releases
                          ↓
Formula builds: uv venv + uv pip install . (into Homebrew's libexec)
                          ↓
Creates:  $(brew --prefix)/bin/zen-ide     (CLI launcher)
          $(brew --prefix)/opt/zen-ide/Zen IDE.app  (.app wrapper)
          /Applications/Zen IDE.app        (symlink)
```

## Setup Guide

### 1. Create the Tap Repository

On GitHub, create a **public** repo named `homebrew-zen-ide` under your user/org.

```bash
# Clone and add the formula
git clone https://github.com/YOUR_USER/homebrew-zen-ide.git
cd homebrew-zen-ide
mkdir -p Formula
cp /path/to/zen-ide/tools/homebrew/zen-ide.rb Formula/zen-ide.rb
```

### 2. Create a Release Tag

```bash
cd /path/to/zen-ide
git tag v0.1.0
git push origin v0.1.0
```

### 3. Get the Tarball SHA256

```bash
curl -sL https://github.com/YOUR_USER/zen-ide/archive/refs/tags/v0.1.0.tar.gz \
  | shasum -a 256
```

Update the `sha256` field in `Formula/zen-ide.rb` with the output.

### 4. Push the Tap

```bash
cd homebrew-zen-ide
git add Formula/zen-ide.rb
git commit -m "Add zen-ide formula v0.1.0"
git push origin main
```

### 5. Install

```bash
brew tap YOUR_USER/zen-ide
brew install zen-ide
```

## What Users Get

| Feature | Works? |
|---------|--------|
| `zen-ide .` from terminal | ✅ |
| Spotlight / Launchpad | ✅ (via .app symlink) |
| Dock icon | ✅ |
| `brew upgrade zen-ide` | ✅ |
| No Gatekeeper warning | ✅ |
| Code signing required | ❌ Not needed |

## Updating the Formula

When you release a new version:

1. Tag and push: `git tag v0.2.0 && git push origin v0.2.0`
2. Get new SHA: `curl -sL .../v0.2.0.tar.gz | shasum -a 256`
3. Update `url` and `sha256` in the formula
4. Push to the tap repo

### Automating with GitHub Actions

Add a workflow to `zen-ide` that on tag push:
1. Computes the tarball SHA256
2. Updates the formula in the tap repo via the GitHub API
3. Users get the update on next `brew upgrade`

## File Reference

- `tools/homebrew/zen-ide.rb` — The Homebrew formula (copy to tap repo)
- `zen_icon.icns` — Bundled into the .app wrapper by the formula

## Future: Homebrew Core

Once the project has enough stars/users, submit the formula to
[Homebrew/homebrew-core](https://github.com/Homebrew/homebrew-core) so users
can install with just `brew install zen-ide` (no tap needed).
Requirement: ≥30 GitHub stars or notable usage.
