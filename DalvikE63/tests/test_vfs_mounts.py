"""Real PC separation: RAM namespace/cache vs persistent C: analogue.

No test here claims Nokia RFs access, EKA2L1, or a compiled Symbian SIS.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dalvik.host import HostError, VFS
from dalvik.ids import FILES
from dalvik.midp_host import MIDPHost
from dalvik.vfs import MountKind

ROOT=Path(__file__).resolve().parents[1]
CATALOG={entry["package"]:entry for entry in json.loads(
    (ROOT / "apks/catalog.json").read_text(encoding="utf-8"))}


class RamAndDriveMountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "build").mkdir(exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(dir=ROOT / "build")
        cls.base=Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def vfs(self,name):
        state=self.base / name
        return VFS(state,ROOT / "apks",CATALOG,state / "imports")

    def test_ram_namespace_and_read_only_system_are_not_written_to_rootfs_disk(self):
        fs=self.vfs("ram")
        mounts={item.guest:item.kind for item in fs.mounts}
        self.assertEqual(mounts["/"],MountKind.RAM)
        self.assertEqual(mounts["/system"],MountKind.BUNDLE_RO)
        self.assertEqual(mounts["/tmp"],MountKind.RAM)
        self.assertEqual(mounts["/cache"],MountKind.RAM)
        self.assertEqual(mounts["/data"],MountKind.C_PRIVATE)
        self.assertEqual(mounts["/sdcard"],MountKind.C_MEDIA)
        self.assertEqual(fs.list("/"),["cache/","data/","sdcard/","storage/","system/","tmp/"])
        self.assertEqual(fs.list("/storage"),["emulated/"])
        self.assertEqual(fs.list("/storage/emulated"),["0/","legacy/"])
        self.assertIn("media/",fs.list("/data"))
        self.assertEqual(fs.list("/data/media"),["0/"])
        self.assertIn("Launcher.apk",fs.list("/system/app"))
        self.assertEqual(fs.resolve("/system/app/Launcher.apk"),ROOT / "apks/Launcher.apk")
        self.assertTrue(fs.system_read("/system/media/audio/ui/lowbattery.wav").startswith(b"RIFF"))
        self.assertFalse((fs.state / "rootfs").exists())
        self.assertFalse((fs.drive / "private/e63os/system").exists())
        with self.assertRaises(HostError):fs.resolve("/system/app/Launcher.apk",write=True,caller=FILES)
        with self.assertRaises(HostError):fs.system_read("/system/media/other.wav")
        with self.assertRaises(HostError):fs.resolve("/system/app/Unknown.apk")
        with self.assertRaises(HostError):fs.resolve("/sdcard/Download/no",write=True)
        with self.assertRaises(HostError):fs.resolve("/sdcard/Download/no",write=True,caller="other")
        with self.assertRaises(HostError):fs.resolve("/data/media/0/Download/no",write=True,caller=FILES)
        with self.assertRaises(HostError):fs.resolve("/storage/emulated/legacy/Download/no",write=True,caller=FILES)
        with self.assertRaises(HostError):fs.resolve("/data/data/"+FILES,write=True,caller=FILES)
        with self.assertRaises(HostError):fs.resolve("/tmp/\x7fbad")

    def test_ram_tmp_and_cache_are_volatile_and_c_drive_is_persistent(self):
        fs=self.vfs("drive")
        fs.temp_write("/tmp/session",b"only RAM")
        fs.temp_write("/cache/index",b"cache")
        self.assertEqual(fs.temp_read("/tmp/session"),b"only RAM")
        self.assertEqual(fs.list("/cache"),["index"])
        self.assertFalse((fs.state / "rootfs/tmp/session").exists())
        with self.assertRaises(HostError):fs.temp_write("/cache/too-large",b"0"*(fs.RAM_FILE_MAX+1))
        with self.assertRaises(HostError):fs.temp_write("/tmp/../escape",b"x")
        large=b"0"*fs.RAM_FILE_MAX
        for i in range(fs.RAM_TOTAL_MAX//fs.RAM_FILE_MAX-1):
            fs.temp_write(f"/cache/bulk{i}",large)
        with self.assertRaisesRegex(HostError,"RAM file/total limit"):
            fs.temp_write("/cache/extra",large)
        fs.temp_write("/tmp/session",b"tiny")  # replacement releases prior RAM budget
        fs.install(FILES)  # VFS service only; app path still gated by PackageInstaller DEX
        self.assertTrue((fs.root / "data/app/FileManager.apk").is_file())
        self.assertTrue(fs.resolve("/sdcard/Music/music.wav").is_file())
        self.assertTrue(str(fs.root).startswith(str(fs.state / "c_drive/private")))
        note=fs.media / "Download" / "note.txt"
        note.write_text("persist",encoding="utf-8")
        restarted=self.vfs("drive")
        self.assertEqual(restarted.ram_root,{})
        with self.assertRaises(HostError):restarted.temp_read("/tmp/session")
        self.assertTrue(restarted.installed(FILES))
        self.assertEqual(restarted.resolve("/sdcard/Download/note.txt").read_text(),"persist")
        self.assertEqual(restarted.resolve("/storage/emulated/0/Download/note.txt"),
                         restarted.resolve("/sdcard/Download/note.txt"))
        self.assertEqual(restarted.resolve("/data/media/0/Download/note.txt"),
                         restarted.resolve("/sdcard/Download/note.txt"))

    def test_installed_copy_must_match_bundle_and_c_drive_conflicts_do_not_hide_files(self):
        fs=self.vfs("corrupt")
        fs.install(FILES)
        apk=fs.root / "data/app/FileManager.apk"
        self.assertTrue(fs.installed(FILES))
        with apk.open("r+b") as stream:
            stream.seek(123)
            byte=stream.read(1)
            stream.seek(123)
            stream.write(bytes([byte[0] ^ 1]))
        self.assertFalse(fs.installed(FILES))
        self.assertFalse(self.vfs("corrupt").installed(FILES))
        state=self.base / "collision"
        old=state / "rootfs/data/keep.txt"
        old.parent.mkdir(parents=True)
        old.write_text("old",encoding="utf-8")
        new=state / "c_drive/private/e63os/data/keep.txt"
        new.parent.mkdir(parents=True)
        new.write_text("new",encoding="utf-8")
        with self.assertRaisesRegex(HostError,"migration conflict"):
            self.vfs("collision")
        self.assertEqual(old.read_text(),"old")
        self.assertEqual(new.read_text(),"new")

    def test_legacy_state_is_migrated_into_private_drive_without_deleting_user_data(self):
        state=self.base / "migration"
        old=state / "rootfs/data"
        (old / "app").mkdir(parents=True)
        (old / "app/FileManager.apk").write_bytes(b"legacy signed APK would be here")
        old_note=old / "media/0/Download/notes.txt"
        old_note.parent.mkdir(parents=True)
        old_note.write_text("user document",encoding="utf-8")
        (state / "flags.json").write_text('{"wifi_demo":1}',encoding="utf-8")
        (state / "j2me_rms.json").write_text('{"J2ME_E63_demo":[1,0,0,0]}',encoding="utf-8")
        fs=self.vfs("migration")
        self.assertEqual(fs.resolve("/sdcard/Download/notes.txt").read_text(),"user document")
        self.assertTrue((fs.root / "data/app/FileManager.apk").is_file())
        self.assertTrue((fs.root / "settings/flags.json").is_file())
        host=MIDPHost(ROOT / "apks/Launcher.apk",state)
        self.assertEqual(host.rms["J2ME_E63_demo"][0],1)
        self.assertTrue(str(host.rms_path).startswith(str(fs.drive)))
        self.assertFalse((state / "rootfs/data").exists())
        self.assertTrue((state / "rootfs").exists()) # never erase unrelated legacy files


if __name__=="__main__":unittest.main()
