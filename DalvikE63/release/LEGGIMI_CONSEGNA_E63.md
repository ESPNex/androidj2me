# Consegna sperimentale Nokia E63 — aggiornamento UI 0.2.2 (27 settembre 2026)

**Esito sul telefono, distinto dalla nuova build:** sul Nokia E63 dell’utente il bridge SIS mostra PIN e `Paired PING`, mentre la MIDlet ottiene `SIS bridge: PONG`. Inoltre la **UI 0.2.1** si avvia, disegna la Home e risponde alle scorciatoie numeriche **con Fn** (anche Quick Settings); il pad direzionale e il tasto funzione sinistro non erano ancora utilizzabili come richiesto. **La UI 0.2.2 qui sotto è compilata e testata su PC, ma non è ancora provata sul Nokia**. Il PONG non dimostra che i due programmi siano già integrati fra loro come OS: bridge e UI sono ancora applicazioni separate.

| File | Byte | SHA-256 |
|---|---:|---|
| **`e63os-0.2.2-back-dpad.sisx` — nuova prova UI** | 635112 | `a6ee53bc09f6c15cb4dd42a648b691ded2932e7430d62a1f39e18cc7656bacca` |
| `e63os.sisx` — UI 0.2.1, copia precedente preservata | 633220 | `1987fd9dccd7bafc75cd1198788e9c72a8267e6193d13d554b522342bdd22193` |
| `e63bridge.sisx` — bridge precedente invariato | 12708 | `8756cf9721fa0e2d35ab6fe4556f094d22acf88680c1e1ac6157a9d601365d35` |
| `Android_J2ME_E63_Bridge.jar` — invariato | 3470271 | `76e47595872e961ccfba4d54eb8c379c0e1c2410cea10e03de3e46a048404503` |
| `Android_J2ME_E63_Bridge.jad` — invariato | 361 | `4e183ec2e023796bced69ddebab5bf61f31a81fb02ffe35041d0982fc354d4db` |
| `DalvikE63_S60FP1_sorgenti_2026-09-27.zip` — **rimosso su richiesta** per liberare 21,55 MiB: fotografia storica sorgenti 0.2.1, non più presente | 22591992 (prima della rimozione) | `0484a0304b68978f827595fb48a54ad1ccdf1d32b0081c00c8074b6c4aec6feb` |
| `e63os_0.2.2_sorgenti_modificati.zip` — patch storica conservata, non è uno ZIP completo | 36152 | `7a7139a1a1f79f7fe1ae96c8a999886bcb10aae2415fd29245d3d281026aef85` |

## Cosa cambia nella UI 0.2.2

- Il **tasto funzione fisico sinistro sotto il display** viene instradato a `E63Canvas.keyPressed(-6)` → `E63Midlet.back()`; **la freccia sinistra del pad resta navigazione**, non Indietro. Il tasto funzione destro passa a Seleziona. I softkey sono intercettati prima della barra comandi Symbian nascosta, con comando CBA di riserva; la Home usa `Exit()` nativo solo come fallback per il lifecycle MIDlet non ancora portato.
- Il runtime DEX esegue i servizi Java ME necessari ai tasti fisici negativi (`Canvas.getKeyName`, stringhe ASCII `toUpperCase`/`indexOf`) e il bytecode originale del debounce `back()` (`System.currentTimeMillis`, registri `long` e istruzioni Dalvik limitate), senza sostituire la UI guest con schermate host. Il mapping del pad accetta scancode S60 o keycode direzionale.
- Il DEX/JAR/APK originale, le immagini, il PIN/PING e il bridge già verificato **non sono modificati**. Questa non è una root Android né un porting completo: Store, Settings e Files nativi, Forms e import dei file Nokia non sono supportati dall’EXE UI parziale.

**Verifiche fatte qui:** `python3 -m unittest discover -s tests -q` → **78 test OK**, incluso `Quick Settings → Indietro → Home` e pad sinistro/destro a livello del DEX. Cross-build GCCE/UREL Symbian 9.2 riuscita; `tools/verify_symbian_sis.py` ha verificato nel SISX 0.2.2 `TargetDevices=0x102032BE` (S60 3rd FP1) e i **5 payload byte per byte** rispetto a EXE/DEX/risorse. Il parser e questi test **non dimostrano i tasti sul dispositivo**, né costituiscono verifica crittografica esterna della firma. Il nuovo certificato di test autofirmato ha impronta SHA-256 `12:8A:BE:1B:28:7B:5E:8B:32:05:5B:9D:06:5C:2C:BA:6F:B3:61:0A:C5:BE:A0:3D:BF:EF:D0:12:00:4A:54:0F`; vale da **27 set 2026 00:38:03 UTC** a **26 set 2028 00:38:03 UTC**. La chiave privata non è nella consegna.

## Prova consigliata sul Nokia

1. **Backup** e controllo data/ora del telefono. Copiare/installare **`e63os-0.2.2-back-dpad.sisx`**, non il vecchio `e63os.sisx`. La nuova firma può causare «Update error» sopra la 0.2.1: solo se necessario e **dopo il backup**, disinstallare la sola vecchia **Android J2ME UI**, quindi riprovare. Non disinstallare per questo il JAR o il bridge già funzionanti.
2. Aprire «Android J2ME UI» dal menu. Se appare la Home, usare **Fn+7** per Quick Settings e poi il **softkey sinistro sotto lo schermo**: atteso ritorno alla Home, *non* il movimento della freccia sinistra del pad. Provare poi pad destra/sinistra: dovrebbe muoversi la selezione tra le icone. **Fn+1** apre Apps; il softkey sinistro dovrebbe tornare alla Home. Per questa prova evitare di aprire Settings/Store col pad centrale: le relative schermate native non sono ancora portate.
3. Se non reagisce, si blocca, l’installer rifiuta l’aggiornamento, o il rendering cambia, inviare **testo esatto dell’errore**, sequenza dei tasti e foto. **Non dichiarare questa 0.2.2 provata sul telefono finché l’utente non conferma.**

**Pulizia successiva su richiesta:** l’archivio integrale **0.2.1** (fotografia sorgenti precedente ai test PONG/Home) è stato verificato con hash e CRC e poi eliminato; si sono conservati progetto corrente `DalvikE63/`, i SISX storici, JAR/JAD e la piccola ZIP patch 0.2.2. La patch contiene solo **otto file**, non basta da sola a ricostruire byte per byte l’intero sorgente storico 0.2.1. Il vecchio `tools/package_symbian_release.py` resta intenzionalmente bloccato: **non** rigenerare la ZIP eliminata automaticamente sotto il limite di workspace.
