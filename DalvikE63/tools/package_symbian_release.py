#!/usr/bin/env python3
"""Rebuild the frozen 0.2.1 full source release, SISX pair and MIDP JAR/JAD.

The 0.2.2 UI key-fix is delivered separately. The historic full 0.2.1 ZIP
was explicitly deleted for snapshot space after SHA/CRC verification: do NOT
use this frozen script to regenerate that 22 MB ZIP or overwrite older SISX.
Its version guard intentionally refuses the current 0.2.2 source tree.
See release/LEGGIMI_CONSEGNA_E63.md.
Never traverse build/, private signing material or locally installed Nokia SDK.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from verify_symbian_sis import platform_ids

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "release"
SOURCE_ZIP = "DalvikE63_S60FP1_sorgenti_2026-09-27.zip"
DOCUMENTS = (
    "README_IT.md", "PORTING_E63_STATO.md", "ARCHITETTURA_IT.md",
    "FEDELTA_ANDROID42_IT.md", "SYMBIAN_TOOLCHAIN_IT.md",
    "adapter_preview.py", "build.py", "package.py", "shell.py",
    "web_preview.py",
)
DIRECTORIES = ("apks", "apps", "assets", "dalvik", "j2me", "symbian", "tests", "tools")
OMIT = {"build", "dist", "out", "release", "__pycache__", ".git", ".venv",
        ".mypy_cache", ".pytest_cache", ".cache", "node_modules"}
PRIVATE_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".jks", ".keystore",
                    ".cer", ".p8", ".pyc", ".class"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def source_files() -> list[Path]:
    listed = [ROOT / name for name in DOCUMENTS]
    for name in DIRECTORIES:
        folder = ROOT / name
        if not folder.is_dir():
            raise FileNotFoundError(folder)
        listed.extend(path for path in folder.rglob("*") if path.is_file())
    allowed: list[Path] = []
    for path in sorted(set(listed)):
        relative = path.relative_to(ROOT)
        if any(part in OMIT for part in relative.parts):
            continue
        if path.suffix.lower() in PRIVATE_SUFFIXES or re.search(
                r"(?:^|[-_.])(private|secret|credential|keypair)(?:[-_.]|$)",
                path.name, flags=re.I):
            raise ValueError(f"private/compiled input in public source release: {relative}")
        if path.is_symlink():
            raise ValueError(f"no symlinks allowed in release: {relative}")
        allowed.append(path)
    for required in ("j2me/classes.dex", "symbian/resources/e63assets.bin",
                     "tools/bootstrap_symbian_fp1.sh", "tools/build_symbian_fp1.sh",
                     "tools/verify_symbian_sis.py", "tests/test_symbian_assets.py"):
        if ROOT / required not in allowed:
            raise ValueError(f"missing source input: {required}")
    return allowed


def certificate_details() -> tuple[str, str, str]:
    """Never reuse certificate metadata from a prior signing session."""
    cert = ROOT / "build/symbian/private/e63-local.cert.pem"
    if not cert.is_file():
        raise FileNotFoundError(f"no local signing certificate for these test builds: {cert}")
    output = subprocess.run(["openssl", "x509", "-in", str(cert),
                             "-noout", "-fingerprint", "-sha256", "-dates"],
                            capture_output=True, text=True, check=True).stdout
    details = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    return (details["sha256 Fingerprint"], details["notBefore"], details["notAfter"])


def build_release() -> list[tuple[str, int, str]]:
    # This historical full-release builder cannot silently overwrite the
    # known-good 0.2.1/bridge deliverables with the separate 0.2.2 key trial.
    if '# {"E63 J2ME DEX UI"}, (0xE0B63E02), 0, 2, 1' not in (
            ROOT / "symbian/e63os.pkg").read_text():
        raise RuntimeError("Frozen 0.2.1 full release: use the separate UI 0.2.2 delivery")
    # Fail closed if the expected real build and original artifacts are missing.
    jar = ROOT / "j2me/Android_J2ME_E63_Bridge.jar"
    jad = ROOT / "j2me/Android_J2ME_E63_Bridge.jad"
    if f"MIDlet-Jar-Size: {jar.stat().st_size}" not in jad.read_text():
        raise ValueError("JAD does not describe the packaged MIDP JAR size")
    with ZipFile(ROOT / "apks/Launcher.apk") as apk:
        if apk.read("classes.dex") != (ROOT / "j2me/classes.dex").read_bytes():
            raise ValueError("signed Launcher APK does not contain the J2ME DEX")
    for name in ("e63os", "e63bridge"):
        path = ROOT / "build/symbian" / f"{name}.sisx"
        if not path.is_file() or path.stat().st_size < 1000 or path.read_bytes()[:4] != struct.pack("<I", 0x10201A7A):
            raise ValueError(f"missing real Symbian 9 SISX: {path}")
        if platform_ids(path) != [0x102032BE]:
            raise ValueError(f"missing target E63 S60 FP1 in signed SISX: {path}")
    fingerprint, valid_from, valid_to = certificate_details()
    files = source_files()
    DEST.mkdir(parents=True, exist_ok=True)
    archive = DEST / SOURCE_ZIP
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6, allowZip64=False) as zf:
        for source in files:
            relative = source.relative_to(ROOT)
            info = ZipInfo((Path("DalvikE63") / relative).as_posix(),
                           date_time=(2026, 9, 27, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = ((0o755 if os.access(source, os.X_OK) else 0o644) << 16)
            zf.writestr(info, source.read_bytes(), compress_type=ZIP_DEFLATED,
                        compresslevel=6)
    for original in (jar, jad, ROOT / "build/symbian/e63os.sisx",
                     ROOT / "build/symbian/e63bridge.sisx"):
        shutil.copyfile(original, DEST / original.name)
    staged = [DEST / name for name in (SOURCE_ZIP, "e63os.sisx",
             "e63bridge.sisx", jar.name, jad.name)]
    # Source contents are allowlisted; ensure no copied private material slipped in.
    with ZipFile(archive) as zf:
        members = zf.namelist()
        if len(members) != len(files) or any(
                any(part in OMIT for part in Path(name).parts) or
                Path(name).suffix.lower() in PRIVATE_SUFFIXES
                for name in members):
            raise AssertionError("release archive has an unexpected/private member")
        if zf.testzip() is not None:
            raise ValueError("corrupt release ZIP")
    rows = [(p.name, p.stat().st_size, sha256(p)) for p in staged]
    manifest = """# Consegna sperimentale Nokia E63 — 27 settembre 2026

**ATTENZIONE: LA UI SISX NON È ANCORA PROVATA SUL TELEFONO.** Il proprietario dell’E63 ha segnalato «Application not compatible with phone — Continue anyway?» installando il precedente `e63os.sisx`. Nei due `.pkg` mancava la dipendenza di piattaforma. Ora entrambi dichiarano **S60 3rd Edition FP1 `0x102032BE`**; un parser SIS9 indipendente verifica tale UID **nel campo TargetDevices dei due SISX firmati**. Questo corregge la causa identificata *nel pacchetto UI*, ma **non prova** che l’avviso UI sparisca o che la UI funzioni. **Riscontro hardware successivo:** il bridge SIS si apre sull’E63, mostra PIN nella console e il JAR MIDP ottiene `SIS bridge: PONG` via loopback. Ciò verifica il solo PING, non la UI grafica o un OS completo. Due pacchetti Symbian 9.2 sono stati crosscompilati GCCE e autofirmati per test locali; non sono un Android 4.2 completo. Fare backup prima di riprovare e valutare firma/autocertificazione e licenza SDK.

| File | Byte | SHA-256 |
|---|---:|---|
"""
    manifest += "\n".join(f"| `{n}` | {size} | `{digest}` |" for n, size, digest in rows)
    manifest += f"""

## Quale file usare

- `e63os.sisx`: **versione 0.2.1**, sostituisce il file precedente 0.2.0. Host Avkon/AppArc con sette percorsi `E63Canvas.paint` del DEX J2ME originale, raster RGB565, clock locale e risorse imballate. Contiene **TargetDevices S60 FP1**: copiare di nuovo *questo file* sul telefono per la prova, non usare una vecchia copia omonima. Installazione/resa della nuova versione **non provate**. UI Store/Files/Login native, Forms, `startApp` e Android rootfs su E63 **non** incluse; non installa un OS vero.
- `e63bridge.sisx`: **versione 0.1.1**, stesso fix di piattaforma; server TCP **PING soltanto** su loopback 127.0.0.1:27463 + launcher “E63 Bridge” nel menu. Sul Nokia E63 l’utente riferisce console con PIN e `SIS bridge: PONG` dalla MIDlet via loopback; la versione esatta del bridge installato non è confermata. Il secondo avvio genera `-14` perché la prima istanza ascolta già sulla porta. Il PIN non è sicuro per operazioni sui file.
- `Android_J2ME_E63_Bridge.jar` e `.jad`: MIDlet separata **MIDP 2.0/CLDC 1.1**, UI completa J2ME del progetto. Conservare JAR e JAD nella stessa cartella; `.jad` indica il JAR e la sua dimensione. Test MicroEmulator solo **headless PC**, non installazione Java ME su E63. Il JAR non sostituisce il SISX OS.
- `DalvikE63_S60FP1_sorgenti_2026-09-27.zip`: sorgenti, sei APK debug con il vero DEX J2ME, JAR/JAD, immagini proprie, pack risorse, test e documenti. **Non** contiene SDK Nokia, toolchain, download firmware, chiave privata né keystore di debug; non include file generati in `build/`. L’archivio è lo snapshot della build precedente alla prova PONG: i `.md` al suo interno possono riportare uno stato hardware più vecchio; per lo stato aggiornato usare questo manifesto e i documenti nella workspace. Non è stato rigenerato per non aumentare l’occupazione del workspace.

**Verificato su questa workstation:** `python3 -m unittest discover -s tests -q`: **77 test OK**; 20 frame originali + 10 frame con pack testati sul PC; GCCE/UREL per tre EXE; **TargetDevices 0x102032BE in entrambi i controller SISX**; SISX OS con **5** payload e bridge con **4** payload tutti uguali ai file sorgenti/SDK in fase di build. Nessuna verifica di firma crittografica esterna né prova di installazione/resa della **UI SISX**; successivamente l’utente ha verificato il PONG del **solo bridge** sull’E63. Certificato di test SHA-256: `{fingerprint}`; valido **{valid_from} → {valid_to}**. Il certificato pubblico è nei SISX; **chiave privata deliberatamente non consegnata**. È stata generata una nuova chiave locale rispetto alla prima consegna: se una versione precedente risulta già installata, un aggiornamento con una firma diversa può essere rifiutato; fare backup e valutare la disinstallazione della sola app di test prima di ritentare. Gli hash SISX diversi in una build futura sono normali (timestamp/firma diversa).

**Prossimo passo per il proprietario dell’E63:** dopo backup e verifica di data/firma, tentare prima l’installazione `e63os.sisx` e raccogliere foto/errori/risultato dei tasti; il bridge PIN/PONG è già stato verificato con il JAR sul suo E63; non reinstallarlo solo per vedere `-14` alla seconda apertura. Un messaggio di firma/capability o una schermata vuota **non** è un test superato: inviare testo esatto, modello/firmware, foto e passi per correggere il porting. Non usare la prova per importare dati privati da C:. Prima di pubblicare a terzi verificare i **diritti di redistribuzione delle risorse WAV preesistenti** nel progetto.
"""
    (DEST / "LEGGIMI_CONSEGNA_E63.md").write_text(manifest, encoding="utf-8")
    return rows


if __name__ == "__main__":
    for filename, size, digest in build_release():
        print(f"{filename:55} {size:>10} {digest}")
    print(f"Release: {DEST / 'LEGGIMI_CONSEGNA_E63.md'}")
    print("Bridge PONG verified on E63; UI SISX 0.2.1 not yet verified on device.")
