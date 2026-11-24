Press **Ctrl+Shift+D** in any app, speak, press it again: the text is typed where you were. Speech recognition runs on your own computer (NVIDIA Parakeet), with no cloud and no account.

- Works in any app on Windows 10/11 and Linux (KDE Plasma, GNOME; Wayland and X11)
- Uses the GPU when it can, the CPU otherwise
- Settings window: shortcut, microphone, start at sign-in, GPU, text clean-up
- If the window you dictated into is gone, the text goes to the clipboard instead of being lost

## Install

**Windows 10/11 (64-bit):** download the `-setup.exe` below and run it. No admin rights needed. Windows SmartScreen may warn because the installer isn't code-signed: click **More info → Run anyway**. Prefer no installer? Use the `-portable.zip`.

**Linux (x86_64, glibc 2.35+, e.g. Ubuntu 22.04+, Debian 12+, Fedora 36+):** download the `.tar.gz`, then:

```sh
tar -xzf quipkey-*-linux-x86_64.tar.gz
cd quipkey-*-linux-x86_64
./install.sh
```

The first start downloads the speech model: about 2.5 GB on Windows with a DirectX 12 graphics card (Quipkey runs on the GPU), otherwise 650 MB (CPU). You can switch between them in the settings. See the [README](../../#readme) for setup details and troubleshooting.

`SHA256SUMS.txt` lists the checksums of the files.
