"""OS structure: guest DEX event -> replaceable package backend.

A fake backend tests the boundary; the production PC backend is still tested
end-to-end in test_ui. This never pretends to be an E63/SIS install.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from dalvik.ids import FILES
from dalvik.os_services import PackageServiceError, UnavailablePackageService
from dalvik.pc_services import PCPackageService
from dalvik.ui_vm import JavaMEUI, MIDLET, UIVMError

ROOT = Path(__file__).resolve().parents[1]
STORE = "Landroid/j2me/edition/StoreState;"


class FakePackageService:
    def __init__(self):
        self.is_installed = False
        self.installs: list[str] = []

    def installed(self, package):
        if package != FILES: raise PackageServiceError("not allowed")
        return self.is_installed

    def install(self, package):
        if package != FILES: raise PackageServiceError("not allowed")
        self.installs.append(package)
        self.is_installed = True


class PackageStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "build").mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.base = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def ui(self, name, packages):
        return JavaMEUI(ROOT / "apks/Launcher.apk", self.base / name, packages=packages)

    @staticmethod
    def start_install(ui):
        ui.tick(2100)
        for key in (-2,-7,-7,-6,-7,-2,-2,-7,-2,-7,-7):
            ui.key(key)
        store=ui.app.fields[MIDLET+"->store:"+STORE]
        assert store.fields.get(STORE+"->installing:Z") == 1

    def test_guest_dex_commits_via_backend_once(self):
        packages=FakePackageService()
        ui=self.ui("fake",packages)
        self.start_install(ui)
        self.assertEqual(packages.installs,[])
        ui.tick(4000)
        self.assertEqual(packages.installs,[FILES])
        self.assertEqual(ui.host.rms["J2ME_E63_demo"][0],1)
        ui.tick(700)
        self.assertEqual(packages.installs,[FILES])
        ui.key(-7)
        self.assertEqual(ui.app.fields[MIDLET+"->screen:I"],8)
        again=self.ui("fake",packages)
        again.tick(2100)
        self.assertEqual(again.app.fields[MIDLET+"->store:"+STORE].fields[STORE+"->installed:Z"],1)

    def test_unavailable_backend_rolls_back_guest_and_rms_then_retries(self):
        packages=UnavailablePackageService()
        ui=self.ui("down",packages)
        self.start_install(ui)
        with self.assertRaisesRegex(UIVMError,"package installation failed"):
            ui.tick(4000)
        store=ui.app.fields[MIDLET+"->store:"+STORE]
        self.assertFalse(store.fields.get(STORE+"->installed:Z",0))
        self.assertFalse(store.fields.get(STORE+"->installing:Z",0))
        self.assertEqual(ui.app.fields[MIDLET+"->installPercent:I"],0)
        self.assertEqual(ui.host.rms["J2ME_E63_demo"][0],0)
        ui.png()
        self.assertIn("INSTALL",[str(c[1]) for c in ui.host.draw_calls if c[0]=="drawString"])
        # Device service becomes available: the original guest activate() can
        # request a new install instead of being trapped behind a false OPEN.
        working=FakePackageService()
        ui.packages=working
        ui.key(-7)
        ui.tick(4000)
        self.assertEqual(working.installs,[FILES])
        self.assertTrue(ui.app.fields[MIDLET+"->store:"+STORE].fields[STORE+"->installed:Z"])

    def test_pc_installer_fails_closed_on_tampered_apk(self):
        altered=self.base / "modified_apks"
        altered.mkdir()
        for file in (ROOT / "apks").iterdir():
            shutil.copyfile(file,altered/file.name)
        package=altered / "PackageInstaller.apk"
        raw=bytearray(package.read_bytes())
        raw[800] ^= 0x01  # invalidate the APK v1 signature
        package.write_bytes(raw)
        backend=PCPackageService(self.base / "tampered", apks=altered)
        with self.assertRaises(PackageServiceError):backend.install(FILES)
        self.assertFalse(backend.installed(FILES))

    def test_pc_package_backend_rejects_other_packages(self):
        service=PCPackageService(self.base / "guard")
        for name in ("com.bad.actor","org.e63.dalvik.systemui", ""):
            with self.subTest(package=name):
                with self.assertRaises(PackageServiceError):service.installed(name)
                with self.assertRaises(PackageServiceError):service.install(name)
        self.assertFalse(service.installed(FILES))


if __name__ == "__main__": unittest.main()
