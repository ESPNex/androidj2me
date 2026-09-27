"""PC implementation of the OS package boundary; never runs on the E63.

Only PackageInstaller.apk's DEX may mutate the sandbox VFS. The UI guest
triggers this service after executing its own StoreState.finishInstall DEX.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile

from .ids import FILES, INSTALLER
from .os_services import PackageServiceError


class PCPackageService:
    def __init__(self, state: Path, apks: Path | None = None):
        # Delay the import: the service contract is independent of DesktopShell.
        from shell import DesktopShell
        state = Path(state)
        self.shell = DesktopShell(apks=apks, state=state, import_root=state / "imports")

    @staticmethod
    def _allowed(package: str) -> None:
        if package != FILES:
            raise PackageServiceError("only FileManager is installable in this prototype")

    def installed(self, package: str) -> bool:
        self._allowed(package)
        return self.shell.vfs.installed(package)

    def install(self, package: str) -> None:
        self._allowed(package)
        if self.installed(package): return  # idempotent on a repeated OS event
        from .host import HostError
        from .vm import VMError
        from .dex import DexError
        from .dex_j2me import J2MEDexError
        from .axml_reader import AXMLError
        try:
            self.shell.active = INSTALLER
            self.shell.refresh()       # executes onStart from PackageInstaller.apk DEX
            self.shell.select(0)       # executes onSelect DEX; its host installs the APK
            if not self.installed(package):
                raise PackageServiceError("PackageInstaller DEX did not install FileManager")
        except (HostError, VMError, DexError, J2MEDexError, AXMLError,
                BadZipFile, OSError, ValueError) as exc:
            raise PackageServiceError("PC PackageInstaller failed: " + str(exc)) from exc
