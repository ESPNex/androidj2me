# Android 4.2.2 compiled AXML fixtures (not app payloads)

Byte-for-byte extracted from the four separately built, AOSP DEV-key-signed
APKs. The ZIP decompressor verified CRC-32; host build and native pins
bind each copied manifest SHA-256 to its original whole APK SHA-256.
They let the on-disk C99 parser tests run even when excluded `build/`
is absent in a later workspace snapshot. They are **not** Android UI.

| File | Original whole APK SHA-256 | AXML SHA-256 |
|---|---|---|
| `Launcher2.axml` | `79dd2e1ab0391d64589dd4caa9689db5d4a95ace4e058b0a890d0a0dc3c803ad` | `3b5ec26b08136227c641713ec635d98e8522a0ecbf872f2c824d28b72142d5f7` |
| `Settings.axml` | `78bca26b22c37f6d6af3306fdd66b0bb835921db407df8104b8dec06cd483afb` | `dc303a3dad78a8a997f17802ce694d74c633496e553635a45f96f19953eff5b2` |
| `PackageInstaller.axml` | `0a11c76216ea931a5cf5a2ae19c3f63cc069431edf2fe84c9049b473ca045d2a` | `5cf674233c8b8dfcf4a06e490c45b009ceb3a8b5c1809550bf8934720e0aba69` |
| `SystemUI.axml` | `0ce434a6a078932604631b311a7a16e8e31ede3d1e682f9fa327722075343bd9` | `fed63236ee146dd92a2427e3e5b432d84f292b77835345499389981941afbb1d` |
