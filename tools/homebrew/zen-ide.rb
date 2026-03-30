class ZenIde < Formula
  desc "Minimalist, performant IDE built with GTK4"
  homepage "https://github.com/AML-dev/zen-ide"
  url "https://github.com/AML-dev/zen-ide/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_ACTUAL_SHA256"
  license "MIT"
  head "https://github.com/AML-dev/zen-ide.git", branch: "main"

  depends_on "gtk4"
  depends_on "gtksourceview5"
  depends_on "libadwaita"
  depends_on "vte3"
  depends_on "gobject-introspection"
  depends_on "pkg-config" => :build
  depends_on "python@3.14"
  depends_on "pygobject3"
  depends_on "uv" => :build
  depends_on :macos

  def install
    venv = libexec/"venv"

    system "uv", "venv", venv,
           "--python", Formula["python@3.14"].opt_bin/"python3.14"

    system "uv", "pip", "install", ".",
           "--python", venv/"bin/python"

    # Determine Homebrew lib path for GLib typelib lookups
    brew_lib = if Hardware::CPU.arm?
      HOMEBREW_PREFIX/"lib"
    else
      HOMEBREW_PREFIX/"lib"
    end

    # CLI launcher — detaches like `code` and `subl`
    (bin/"zen-ide").write <<~BASH
      #!/bin/bash
      export DYLD_FALLBACK_LIBRARY_PATH="#{brew_lib}:${DYLD_FALLBACK_LIBRARY_PATH}"
      export PYTHON_JIT=1
      VENV_PYTHON="#{venv}/bin/python"
      ENTRY="#{venv}/lib/python3.14/site-packages/src/zen_ide_window.py"
      nohup "$VENV_PYTHON" "$ENTRY" "$@" </dev/null >/dev/null 2>&1 &
      disown
    BASH

    # Create macOS .app wrapper for Dock / Spotlight / Launchpad
    create_app_bundle
  end

  def create_app_bundle
    app_dir = prefix/"Zen IDE.app/Contents"
    macos_dir = app_dir/"MacOS"
    resources_dir = app_dir/"Resources"

    macos_dir.mkpath
    resources_dir.mkpath

    # Info.plist
    (app_dir/"Info.plist").write <<~XML
      <?xml version="1.0" encoding="UTF-8"?>
      <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
        "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
      <plist version="1.0">
      <dict>
        <key>CFBundleName</key>
        <string>Zen IDE</string>
        <key>CFBundleDisplayName</key>
        <string>Zen IDE</string>
        <key>CFBundleIdentifier</key>
        <string>com.zen-ide.app</string>
        <key>CFBundleVersion</key>
        <string>#{version}</string>
        <key>CFBundleShortVersionString</key>
        <string>#{version}</string>
        <key>CFBundleExecutable</key>
        <string>zen-ide</string>
        <key>CFBundleIconFile</key>
        <string>zen_icon</string>
        <key>CFBundlePackageType</key>
        <string>APPL</string>
        <key>NSHighResolutionCapable</key>
        <true/>
        <key>CFBundleDocumentTypes</key>
        <array>
          <dict>
            <key>CFBundleTypeName</key>
            <string>Text Document</string>
            <key>CFBundleTypeRole</key>
            <string>Editor</string>
            <key>LSHandlerRank</key>
            <string>Alternate</string>
            <key>LSItemContentTypes</key>
            <array>
              <string>public.text</string>
              <string>public.plain-text</string>
              <string>public.source-code</string>
            </array>
          </dict>
          <dict>
            <key>CFBundleTypeName</key>
            <string>Folder</string>
            <key>CFBundleTypeRole</key>
            <string>Viewer</string>
            <key>LSHandlerRank</key>
            <string>Alternate</string>
            <key>LSItemContentTypes</key>
            <array>
              <string>public.folder</string>
            </array>
          </dict>
        </array>
      </dict>
      </plist>
    XML

    # Copy icon if available in the source tree
    icon_src = buildpath/"zen_icon.icns"
    cp icon_src, resources_dir/"zen_icon.icns" if icon_src.exist?

    # App launcher — calls the Homebrew bin wrapper
    (macos_dir/"zen-ide").write <<~BASH
      #!/bin/bash
      exec "#{bin}/zen-ide" "$@"
    BASH
    (macos_dir/"zen-ide").chmod 0755
  end

  def post_install
    # Symlink .app into /Applications for Spotlight / Launchpad
    app_src = prefix/"Zen IDE.app"
    app_dst = Pathname("/Applications/Zen IDE.app")
    if app_src.exist? && !app_dst.exist?
      app_dst.make_symlink(app_src)
      ohai "Symlinked 'Zen IDE.app' into /Applications"
    end
  end

  def caveats
    <<~EOS
      Zen IDE has been installed!

      CLI usage:
        zen-ide .              # open current directory
        zen-ide file.py        # open a file
        zen-ide my.zen-workspace  # open a workspace

      The app is also available in Spotlight and Launchpad.
      To remove the /Applications symlink on uninstall:
        rm "/Applications/Zen IDE.app"
    EOS
  end

  test do
    # Verify the venv and entry point exist
    venv_python = libexec/"venv/bin/python"
    assert_predicate venv_python, :exist?
    assert_match "Python 3.14", shell_output("#{venv_python} --version")
  end
end
