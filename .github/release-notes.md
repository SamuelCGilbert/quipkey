## Install

**Windows 10/11 (64-bit):** download the `-setup.exe` below and run it. No admin rights needed. Windows SmartScreen may warn because the installer isn't code-signed: click **More info → Run anyway**. Prefer no installer? Use the `-portable.zip`.

**Linux (x86_64, glibc 2.35+, e.g. Ubuntu 22.04+, Debian 12+, Fedora 36+):** download the `.tar.gz`, then:

```sh
tar -xzf hotmic-*-linux-x86_64.tar.gz
cd hotmic-*-linux-x86_64
./install.sh
```

The first start downloads the speech model (about 650 MB). See the [README](../../#readme) for setup details and troubleshooting.

`SHA256SUMS.txt` lists the checksums of the files.
