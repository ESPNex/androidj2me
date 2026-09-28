"""Conservative gates for the distinct, size-limited AOSP E63 core SISX.

No unit test here is a Nokia E63 installation test or Android Activity boot.
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.build_aosp42_e63_core_preview_sis import LIMIT, OUTPUT
from tools.make_aosp42_e63_core_pkg import (
    APP, BOOT_FILES, BOOT_JARS, NEW_PKG, OLD_PKG, OLD_SHA,
    _expected, get_reference, sha256,
)
from tools.verify_symbian_sis import extract, platform_ids

ROOT = Path(__file__).resolve().parents[1]
CORE_SHA = "2207f1cd2d1678d2047cae8a51b66f48342e856d703490768f81ae99caf31706"
CORE_BYTES = 16_220_160
CORE_INSTALLED = 30_019_093


class CorePreviewChecks(unittest.TestCase):
    def test_original_release_pins_and_module_split(self):
        entries, original_rows = _expected()  # no downloads/SDK required
        self.assertEqual(len(original_rows), 44)
        self.assertEqual(len(entries), 21)
        self.assertEqual([n for n in BOOT_JARS if n == "framework-res.apk"], [])
        self.assertEqual(len(BOOT_FILES), 11)
        self.assertEqual(OLD_SHA,
                         "4c9a312e19789c394e072825f7b9e95a82efbaa9c6dfcd0bd30cf6a033db55ff")
        original = OLD_PKG.read_text()
        core = NEW_PKG.read_text()
        self.assertIn('(0xE0B63E04), 0, 6, 0', original)
        self.assertIn('(0xE0B63E04), 0, 7, 0', core)
        rows = [line for line in core.splitlines() if line.startswith('"')]
        self.assertEqual(len(rows), 24)
        self.assertEqual(rows, original_rows[:3] + original_rows[10:20] +
                         original_rows[21:32])
        self.assertNotIn('"images565.bin"', core)
        self.assertNotIn('Launcher2.apk', core)
        self.assertNotIn('framework-res.apk', core)
        self.assertNotIn('FileManager.apk', core)
        self.assertTrue(all('/dev/binder' not in row for row in rows))
        self.assertTrue(all(row.split('" - "')[1].startswith('C:\\private\\E0B63E04')
                            for row in rows[3:]))

    def test_arm_source_explicitly_reports_unavailable_ui_without_legacy_apks(self):
        source = (APP / "e63android_app.cpp").read_text()
        self.assertIn('#ifdef E63_CORE_PREVIEW', source)
        self.assertIn('AOSP UI module absent; NO Activity', source)
        self.assertIn('Android Activity assente; core DEX/JNI/IPC', source)
        self.assertIn('UI/resources: moduli non installati', source)
        self.assertIn('if (key==\'*\') { ProbeAospNativePid()', source)
        self.assertIn('if (key==\'0\') { ProbeAospDex()', source)
        self.assertIn('if (key==\'3\') { ProbeAospFrameworkPoint()', source)
        self.assertIn('ProbeBinderAbsent();return EKeyWasConsumed;', source)
        self.assertIn('#ifndef E63_CORE_PREVIEW\n        ReadImagesL();', source)
        self.assertIn('TRAPD(bootError,OpenL(PKG_HOME,EFalse));', source)
        self.assertNotIn('MACRO           E63_CORE_PREVIEW',
                         (APP / "e63android.mmp").read_text())
        self.assertIn('MACRO           E63_CORE_PREVIEW',
                      (ROOT / "tools/build_aosp42_e63_core_preview_sis.py").read_text())

    def test_unpinned_or_malformed_full_image_is_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as scratch:
            false = Path(scratch) / "fake.sisx"
            false.write_bytes(b"SISX" * 128)
            with self.assertRaises(ValueError):
                get_reference(false)

    def test_preserved_signed_asset_is_below_decimal_limit_and_payloads_pinned(self):
        if not OUTPUT.exists():
            self.skipTest("core SISX is not built; source-stage tests still run")
        self.assertLess(OUTPUT.stat().st_size, LIMIT)
        self.assertEqual(OUTPUT.stat().st_size, CORE_BYTES)
        self.assertEqual(sha256(OUTPUT.read_bytes()), CORE_SHA)
        self.assertEqual(platform_ids(OUTPUT, diagnostic=True), [0x102032BE])
        packaged = extract(OUTPUT, core_preview=True)
        self.assertEqual(len(packaged), 24)
        self.assertEqual(sum(map(len, packaged)), CORE_INSTALLED)
        self.assertIn("E63 AOSP core: experimental".encode("utf-16-le"),
                      packaged[0])
        expected, _ = _expected()
        for at, ((_, _, (size, digest)), payload) in enumerate(zip(expected,
                                                      packaged[3:]), start=3):
            with self.subTest(payload=at):
                self.assertEqual(len(payload), size)
                self.assertEqual(hashlib.sha256(payload).hexdigest(), digest)
        self.assertNotEqual(packaged[0][:16], b"\0" * 16)


if __name__ == "__main__":
    unittest.main()
