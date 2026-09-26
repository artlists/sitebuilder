# SiteBuilder desktop build (Windows + macOS)
#
# Usage:
#   pyinstaller app/sitebuilder.spec
#
# Windows: single-file console exe (dist/SiteBuilder.exe) — shows the admin
#          URL and credentials, keeps the server alive until closed.
# macOS:   app bundle (dist/SiteBuilder.app) — windowed, opens the browser
#          automatically; credentials are written to ADMIN-CREDENTIALS.txt.

import sys

datas = [
    ("engine/build.py", "engine"),
    ("engine/template.html", "engine"),
    ("engine/admin/server.py", "engine/admin"),
    ("engine/admin/publish.sh", "engine/admin"),
    ("engine/admin/init_password.py", "engine/admin"),
    ("engine/admin/static", "engine/admin/static"),
    ("starter", "starter"),
]

a = Analysis(
    ["app/launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="SiteBuilder",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="SiteBuilder",
    )
    app = BUNDLE(
        coll,
        name="SiteBuilder.app",
        icon=None,
        bundle_identifier="com.sitebuilder.app",
        info_plist={
            "CFBundleName": "SiteBuilder",
            "CFBundleDisplayName": "SiteBuilder",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="SiteBuilder",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )