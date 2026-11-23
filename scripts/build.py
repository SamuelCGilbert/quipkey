"""Build release artifacts for the current OS into dist/.

    python scripts/build.py            # PyInstaller app + packages
    python scripts/build.py --no-package

Windows: dist/<app>-<ver>-windows-x64-setup.exe (Inno Setup, if ISCC is found) and
         dist/<app>-<ver>-windows-x64-portable.zip
Linux:   dist/<app>-<ver>-linux-x86_64.tar.gz (app folder + install.sh)

The app name, version etc. come from src/<package>/meta.py, so a rename doesn't touch this file.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
BUILD = ROOT / "build"
DIST = ROOT / "dist"


def find_package() -> str:
    metas = glob.glob(str(SRC / "*" / "meta.py"))
    if len(metas) != 1:
        raise SystemExit(f"expected exactly one src/<package>/meta.py, found {metas}")
    return Path(metas[0]).parent.name


PKG = find_package()
META: dict = {}
exec((SRC / PKG / "meta.py").read_text(encoding="utf-8"), META)
APP, DISPLAY, VERSION, APP_ID = META["APP_NAME"], META["APP_DISPLAY_NAME"], META["VERSION"], META["APP_ID"]
IS_WIN = sys.platform == "win32"


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def make_icon() -> Path:
    sys.path.insert(0, str(SRC))
    icon_mod = __import__(f"{PKG}.icon", fromlist=["save_ico"])
    BUILD.mkdir(exist_ok=True)
    ico = BUILD / f"{APP}.ico"
    icon_mod.save_ico(ico)
    png = BUILD / f"{APP}.png"
    icon_mod.make_icon(256).save(png)
    return ico


def version_file() -> Path:
    nums = [int(x) for x in re.findall(r"\d+", VERSION)[:3]] + [0, 0, 0]
    v = tuple(nums[:3] + [0])
    path = BUILD / "version_info.txt"
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{DISPLAY} contributors'),
      StringStruct('FileDescription', '{DISPLAY} dictation'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', '{APP}'),
      StringStruct('LegalCopyright', 'GPL-3.0-or-later'),
      StringStruct('OriginalFilename', '{APP}.exe'),
      StringStruct('ProductName', '{DISPLAY}'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
""", encoding="utf-8")
    return path


def find_portaudio() -> Path:
    ldconfig = shutil.which("ldconfig") or "/sbin/ldconfig"
    out = subprocess.run([ldconfig, "-p"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "libportaudio.so.2 " in line and "x86-64" in line:
            return Path(line.split("=>")[-1].strip())
    raise SystemExit("libportaudio.so.2 not found; install libportaudio2")


def pyinstaller(ico: Path) -> Path:
    entry = BUILD / "entry.py"
    entry.write_text(f"from {PKG}.cli import main\n\nmain()\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
           "--name", APP, "--distpath", DIST / "pyinstaller", "--workpath", BUILD / "pyinstaller",
           "--specpath", BUILD, "--paths", SRC,
           "--collect-data", "onnx_asr", "--copy-metadata", "onnx-asr",
           "--collect-submodules", PKG,
           "--exclude-module", "pytest", "--exclude-module", "matplotlib",
           "--exclude-module", "IPython", "--exclude-module", "torch",
           "--exclude-module", "hf_xet"]  # downloads use plain HTTPS (see transcriber.py)
    if IS_WIN:
        cmd += ["--windowed", "--icon", ico, "--version-file", version_file(),
                "--hidden-import", "pystray._win32"]
    else:
        # Bundle PortAudio (not on every desktop). Not libasound: ALSA plugins (the PipeWire/
        # Pulse bridge) must match the system's libasound, so that one comes from the system.
        cmd += ["--add-binary", f"{find_portaudio()}:."]
    run(cmd + [entry])
    out = DIST / "pyinstaller" / APP
    if not IS_WIN:
        for f in (out / "_internal").glob("libasound.so*"):
            f.unlink()
    return out


def package_windows(app_dir: Path, ico: Path):
    base = f"{APP}-{VERSION}-windows-x64"
    zpath = DIST / f"{base}-portable.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(app_dir.rglob("*")):
            z.write(f, Path(APP) / f.relative_to(app_dir))
        for extra in ("README.md", "LICENSE"):
            z.write(ROOT / extra, Path(APP) / extra)
    print("wrote", zpath)
    iscc = shutil.which("iscc") or next(
        (p for p in (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
                     r"C:\Program Files\Inno Setup 6\ISCC.exe") if os.path.exists(p)), None)
    if not iscc:
        print("ISCC (Inno Setup 6) not found; skipping the installer", file=sys.stderr)
        return
    run([iscc, "/Q", f"/DAppName={APP}", f"/DAppDisplayName={DISPLAY}", f"/DAppVersion={VERSION}",
         f"/DAppId={APP_ID}", f"/DRepoUrl={META['REPO_URL']}", f"/DDistDir={app_dir}",
         f"/DIconFile={ico}", f"/DRootDir={ROOT}", f"/DOutputDir={DIST}",
         f"/DOutputBase={base}-setup", ROOT / "packaging" / "windows" / "installer.iss"])


def package_linux(app_dir: Path):
    base = f"{APP}-{VERSION}-linux-x86_64"
    stage = BUILD / base
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(app_dir, stage / APP, symlinks=True)
    subs = {"@APP_NAME@": APP, "@APP_DISPLAY_NAME@": DISPLAY, "@APP_ID@": APP_ID,
            "@VERSION@": VERSION, "@REPO_URL@": META["REPO_URL"]}
    text = (ROOT / "packaging" / "linux" / "install.sh").read_text(encoding="utf-8")
    for k, v in subs.items():
        text = text.replace(k, v)
    (stage / "install.sh").write_text(text, encoding="utf-8")
    (stage / "install.sh").chmod(0o755)
    for extra in ("README.md", "LICENSE"):
        shutil.copy(ROOT / extra, stage / extra)
    shutil.copy(BUILD / f"{APP}.png", stage / f"{APP}.png")
    tpath = DIST / f"{base}.tar.gz"
    with tarfile.open(tpath, "w:gz") as t:
        t.add(stage, arcname=base)
    print("wrote", tpath)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-package", action="store_true", help="only run PyInstaller")
    args = ap.parse_args()
    DIST.mkdir(exist_ok=True)
    ico = make_icon()
    app_dir = pyinstaller(ico)
    if args.no_package:
        return
    if IS_WIN:
        package_windows(app_dir, ico)
    else:
        package_linux(app_dir)


if __name__ == "__main__":
    main()
