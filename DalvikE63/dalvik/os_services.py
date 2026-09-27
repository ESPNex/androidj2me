"""Boundary between DEX-driven UI and APK package management.

The guest J2ME bytecode decides *when* INSTALL/OPEN occurs. A device backend
must perform the resulting install and report the authoritative state. This
protocol deliberately knows nothing about Python screens or HTML.
"""
from __future__ import annotations

from typing import Protocol

from .ids import FILES


class PackageServiceError(RuntimeError):
    """No install happened; the caller must not report OPEN to the guest."""


class PackageService(Protocol):
    def installed(self, package: str) -> bool:
        """Return the real package state, not the guest's cached StoreState."""
        ...

    def install(self, package: str) -> None:
        """Install a verified APK or raise PackageServiceError; no fake success."""
        ...


class UnavailablePackageService:
    """Fail-closed placeholder for an E63 backend until device code exists.

    This is intentionally NOT an installer. Passing it to JavaMEUI allows
    testing failure recovery without claiming a working SIS or E63 runtime.
    """
    def installed(self, package: str) -> bool:
        if package != FILES: raise PackageServiceError("package is not on the allowlist")
        return False

    def install(self, package: str) -> None:
        if package != FILES: raise PackageServiceError("package is not on the allowlist")
        raise PackageServiceError("device APK installer not implemented")
