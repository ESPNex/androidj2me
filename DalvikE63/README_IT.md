# DalvikE63 — DEX Java Android e precedente UI J2ME su E63

**Nuova base Symbian modulare (preview 0.7):** [`release/experiments/e63android-aosp42-core-preview.sisx`](release/experiments/e63android-aosp42-core-preview.sisx) = **16.220.160 byte**, SHA-256 `2207f1cd2d1678d2047cae8a51b66f48342e856d703490768f81ae99caf31706`; 24 payload, circa 30 MB estratti su C:. Contiene i dieci JAR AOSP/DEX autentici, JNI e Binder diagnostici; **non** contiene ancora Launcher2/SystemUI/`framework-res` o un'Activity Android avviabile, e non è testata sul Nokia. La [0.6 integrale](https://github.com/ESPNex/androidj2me/releases/tag/v0.6-preview) e tutte le release storiche rimangono preservate. [Dimensioni, limiti e percorso verso l'Android mirato E63](docs/e63_modular_size_budget.md) · [avvertenze 0.7](release/experiments/LEGGIMI-E63-CORE-SOTTO20MB.md). La 0.7 condivide UID/SID con la 0.2/0.6 ma ha un nuovo certificato: **backup completo prima di qualsiasi installazione**.

**Stato storico della 0.6 integrale:** [preview v0.6 su GitHub](https://github.com/ESPNex/androidj2me/releases/tag/v0.6-preview) · [JNI, Binder e limiti reali](docs/aosp42_vm_jni_binder_status.md) · [avvertenze prima dell'installazione](release/experiments/LEGGIMI-JNI-BINDER-PREVIEW.md). Il SISX è compilato per S60 FP1 e include DEX AOSP autentico, JNI e IPC Binder *parziali*; **non** avvia Android 4.2 completo, SystemServer, Activity o View. Il nuovo ramo **non è stato provato sul Nokia**. Suite PC: **143 test, 3 saltati** nel checkout senza i tool temporanei in `build/`; **153 test, 1 saltato** nella precedente verifica dopo il bootstrap AOSP/SDK. Queste verifiche non sostituiscono la prova hardware. `/system` guest è persistente e di sola lettura su C:, non interamente in RAM. Il precedente SISX preview è andato perso con la sua chiave effimera: il nuovo asset è rigenerato e ha SHA diverso. **Release 0.2, APK/JAR/SISX storici e progetto MIDP restano conservati.** Gli stadi precedenti sono documentati in [oggetti DEX AOSP](OGGETTI_AOSP42_E63_IT.md), [framework](RUNTIME_NATIVO_E63_IT.md), [UI/APK](UI_AOSP42_STATO_IT.md) e [primo aggancio](FRAMEWORK42_AGGANCIO_IT.md).

**Build 0.2 conservata (storica, non beta):** [nota e istruzioni E63 0.2](release/LEGGIMI_E63_ANDROID_JAVA_0.2.md) · [SISX Activity/Unicode/servizi](release/e63android-0.2-activity-unicode-services-test.sisx). Il target E63 interpreta ora realmente i metodi DEX `Main/GuestActivity` con shim framework ristretti, parser Unicode MUTF-8 e servizi file limitati alla C: privata/import consentito; **non** è Android 4.2 completo e non è stato testato sul Nokia. La precedente 0.1 e tutte le release J2ME restano in `release/`. Lo ZIP ridondante della fotografia 0.2.1 è stato cancellato su autorizzazione dopo verifica CRC/SHA; rimangono sorgenti correnti, patch, SISX e JAR. La stima ~111 MiB si riferiva alla precedente fotografia; gli artefatti pesanti attuali restano in `build/` escluso. [Stato del ramo storico](ANDROID_JAVA_E63_IT.md).

**Percorso 0.1 conservato (storico, non descrive la 0.2):** [sei APK Android **Java/Activity** con asset propri e interprete del loro vero DEX](ANDROID_JAVA_E63_IT.md). Sorgenti `android_java/`, APK debug firmati in [`apks_android/`](apks_android/), interpreti Python e **C99**, pin SHA-256 e RGB565. Dopo l’accettazione della licenza Nokia è stato **crosscompilato ARM/GCCE e firmato** un target AppArc Symbian separato: [**`e63android-0.1-java-apk-preview.sisx`**](release/e63android-0.1-java-apk-preview.sisx) con i sei APK interi, SID `0xE0B63E04`, `TargetDevices=0x102032BE` e dieci payload verificati. **92 test PC**; non è ancora stato eseguito il nuovo SISX su E63 né alcun nuovo APK su Android reale. Non è un runtime Android completo: INSTALL/FileManager Nokia restano disabilitati. La vecchia UI/SISX/JAR rimane intatta.

## Percorso storico J2ME e SISX già consegnati

**Stato al 27 settembre 2026.** Il PC esegue l’interfaccia **originale del porting J2ME**, convertita in `classes.dex` (non ridisegnata da un adattatore). `E63Midlet` gestisce schermate, tasti, ticker e Form nella VM Python su PC. Lo stile ispirato a **Jelly Bean/Android 4.2** include barre, dock/drawer, notifiche, Quick Settings e Recenti guest. [Nove screenshot e limiti](FEDELTA_ANDROID42_IT.md) · [anteprima Python](assets/preview_android42.png) · [20 confronti RGB565 PC](assets/preview_rgb565_full_pc.png). L’interprete DEX è nostro, non un motore Android incorporato né un formato AOT. **Tappa hardware:** l’E63 ha mostrato «Application not compatible with phone — Continue anyway?» per il **primo** `e63os.sisx` (0.2.0). Mancava la dipendenza di piattaforma nei `.pkg`; la nuova build ARM/autofirmata `e63os.sisx` **0.2.1** e `e63bridge.sisx` **0.1.1** dichiara S60 3rd FP1 `0x102032BE` e il controller dei SISX lo conferma. **Il bridge MIDP↔SIS ha ora restituito `SIS bridge: PONG` sul Nokia E63 fisico** (PIN nella console; una seconda istanza dà `-14` perché la prima tiene la porta). **La UI 0.2.1 è stata poi avviata sull’E63: Home visibile e scorciatoie numeriche funzionanti con Fn; il pad e il softkey sinistro non reagivano come richiesto. La nuova UI 0.2.2 (`release/e63os-0.2.2-back-dpad.sisx`) porta il fix dei tasti, ancora da provare sul telefono.** [Istruzioni toolchain, hash, licenza e limiti](SYMBIAN_TOOLCHAIN_IT.md).

**Stato del porting:** [ARCHITETTURA_IT.md](ARCHITETTURA_IT.md) distingue il runtime PC dall’host E63 **parziale**; [PORTING_E63_STATO.md](PORTING_E63_STATO.md) documenta storage, prove e gate hardware. `symbian/runtime/dex_vm.c` interpreta il **DEX originale di StoreState**; `ui_event_vm.c` esegue eventi e il vero **`E63Canvas.paint(Graphics)` per sette schermate guest** (Home, cartella vuota, spegnimento, Apps/Widgets, notifiche, Quick Settings e Recenti), compresi status/nav, `clock()`, batteria e `<clinit>` dei glifi. `rgb565_painter.c` implementa lente circolare, RGBA, RGB565 e commit atomico. Venti confronti dei frame PC a 320×240/220×180 sono pixel-identici al guest Python. `symbian/e63os_app.cpp` collega **questa stessa VM/raster compilata ARM** a un `CFbsBitmap`/Window Server, tasti E63, clock locale e pack di PNG/font derivato dal progetto; **dieci** confronti aggiuntivi PC con il pack sono pixel-identici. Le verifiche pixel-identiche restano prove PC; sull’E63 la Home 0.2.1 e le scorciatoie Fn sono osservate. JAR/JAD 1.2.1, sorgenti J2ME e `classes.dex` restano invariati; i sei APK sono firmati debug e possono avere firme diverse a ogni ricostruzione. Mancano `startApp`, tutte le altre schermate native C99, Forms, file reali/`RFs`, gestione pacchetti sul Nokia e prova dei **nuovi tasti della UI 0.2.2** sul dispositivo (la 0.2.1 ha già mostrato Home/Fn e il bridge ha dato PONG).

Il vecchio JAR/JAD MIDP 1.0.3 resta intatto nel progetto precedente. Qui il porting MIDP 2.0/CLDC 1.1 è la versione **1.2.1**, con schermata SIS Bridge e client loopback. La UI è adattata ai 320×240 dell’E63, con testo Email/Password/Search, INSTALL → OPEN, Back/Home best effort e batteria `?` quando non disponibile; Wi-Fi e Store sono simulati nel prototipo. Nella **1.2.1** i quattro riquadri Quick Settings condividono il colore del pannello, l’orario è allineato alla batteria e la lente di ricerca è circolare: il disegno resta nel guest J2ME convertito, non negli adattatori.

## Come funziona la UI J2ME della release precedente

```text
browser: tasti / click / testo Form  ─► web_preview.py (solo terminale)
                                        │
                                        ▼
                               JavaMEUI + interprete DEX
                              dalvik/ui_vm.py · dex_ops.py
                                        │
              classes.dex: E63Midlet.startApp, E63Canvas.paint,
              keyPressed, pointerPressed, commandAction, tickLoop,
              StoreState.finishInstall, BridgeClient.ping ...
                                        │
                                        ▼
                       servizi MIDP host (dalvik/midp_host.py)
                      Graphics → PNG · immagini APK · RMS · clock
                      Form/TextField · SocketConnection TCP locale
                                        │
                          INSTALL concluso dal guest DEX
                                        ▼
                   PackageService → PackageInstaller.apk DEX → VFS PC
```

Il browser riceve **solo i PNG prodotti dalla Canvas convertita**, non markup HTML delle singole schermate. Un test cambia la stringa `Play Store` **nel solo `classes.dex`**, ricalcola l'integrità DEX e osserva stringa e pixel diversi: la UI dipende dal bytecode originale, non da una sua copia nell'host. Il runtime non importa le sorgenti degli adattatori. La navigazione verificata attraversa metodi J2ME reali (il DEX attuale contiene 118 metodi con codice); ciò **non significa** che tutti i metodi o tutto Dalvik siano supportati. Istruzioni/metodi non implementati falliscono anziché venire sostituiti silenziosamente da schermate hardcoded.

Il nuovo `web_preview.py` è l'anteprima primaria. `adapter_preview.py` conserva la vecchia anteprima basata sugli adattatori **solo per regressioni/diagnostica**, non è la UI principale. Gli adattatori `classes2.dex` rimangono per i servizi del precedente host (`shell.py`, fra cui installazione e VFS), ma **non dipingono** la nuova anteprima. I Form MIDP sono presentati come controlli input nativi dal servizio host: il testo torna a `TextField.setString` e al `E63Midlet.commandAction` convertito, non viene interpretato come una schermata HTML equivalente.

### Gli APK storici J2ME (`apks/`, non `apks_android/`)

| Artefatto | Ruolo nel prototipo |
|---|---|
| [Launcher.apk](apks/Launcher.apk) | Manifest con entry `android.j2me.edition.E63Midlet`; avvia la UI originale nel nostro runtime PC. |
| [Settings.apk](apks/Settings.apk) | Servizio/adattatore compatibile con il precedente host; Settings a schermo è disegnato dalla Canvas originale del Launcher. |
| [Store.apk](apks/Store.apk) | Servizio/adattatore compatibile; Store a schermo, ricerca e progress INSTALL provengono dal DEX J2ME originale. |
| [SystemUI.apk](apks/SystemUI.apk) | Servizio del precedente host; errore `com.android.systemui` **simulato** e dipinto dal Canvas originale. |
| [PackageInstaller.apk](apks/PackageInstaller.apk) | Il suo DEX viene invocato nel PC dopo `StoreState.finishInstall` del J2ME e copia `FileManager.apk` nella VFS. |
| [FileManager.apk](apks/FileManager.apk) | App installata nella VFS PC; schermata Files disegnata dal Canvas originale. Il servizio VFS supporta CRUD/import dalla sandbox PC, **non ancora tramite la schermata J2ME**. |

**Tutti e sei gli APK** contengono lo stesso `classes.dex` J2ME convertito, con 9 classi originali e 118 metodi con codice, più un piccolo `classes2.dex` specifico per i servizi legacy, `AndroidManifest.xml` binario, immagini MIDP e firma **v1 debug** JDK. Sono ZIP/APK reali, **non JAR rinominati**; per tracciabilità vedere `j2me/source_provenance.json` e `assets/j2me-provenance.json` nell'APK. Tuttavia i cinque APK ausiliari **non** sono cinque UI J2ME indipendenti: la UI integrata parte dal MIDlet del Launcher e usa i servizi VFS/installer separati. Il MIDlet non è una `android.app.Activity` e Android 4.2 non offre MIDP: manifest `minSdk=17` e firma valida **non** implicano che gli APK girino su Android 4.2.

Il File Manager del **vecchio host CLI** opera su file reali **della sandbox PC** tramite `--import-root`; l’UI `E63Canvas.paintFiles` presenta le voci statiche J2ME e mostra l’errore SystemUI simulato **solo nel runtime PC**. Import da **Nokia C:**, CRUD della UI guest, audio reale e collegamento a file telefonici sono lavori futuri. La root del PC è un namespace RAM: `/tmp` e `/cache` volatili, `/system` sola lettura; APK, RMS e flag persistono sotto `state/c_drive` **del PC**. Il nuovo SIS UI installa in `C:\\private\\E0B63E02\\` soltanto DEX e pack di risorse: non monta una root Android. Il renderer Window Server esiste in `e63os_app.cpp`, **ma** VFS/RAM C99 non sono collegati a `RFs` o alla VM nativa.

## Ponte MIDlet ↔ componente Symbian: cosa è davvero verificato

- `j2me/src/android/j2me/edition/BridgeClient.java` è compilato sia nel JAR MIDP sia nel DEX. **Settings → SIS Bridge** apre un Form con PIN a sei cifre mascherato. L'**effettivo DEX `BridgeClient.ping`** invia il frame `E63BRIDGE/1\tAUTH\t<PIN>\tPING\n` a `socket://127.0.0.1:27463` tramite lo shim `SocketConnection` TCP loopback del PC. Anche i `Runnable.run`, gli handler guest per le eccezioni e l'aggiornamento dello `StringItem` sono eseguiti da DEX. Testato contro il **nucleo C reale** `symbian/bridge_protocol.c`: PONG con PIN valido, rifiuto con PIN errato; senza server la UI guest mostra `Unavailable: java.io.IOException`. È testato inoltre il `.class` MIDP con lo stesso nucleo C tramite shim di test.
- `symbian/e63bridge.cpp` è ora **compilato** con SDK S60 FP1/GCCE: usa `RSocketServ`/`RSocket`, bind a `KInetAddrLoop`, PIN temporaneo e limite di tentativi. Il pacchetto autofirmato `e63bridge.sisx` include anche `e63bridge_launch.exe` registrato nel menu AppArc. `NetworkServices` è presente nell’immagine E32. **Testato dall’utente su Nokia E63:** avvio del bridge SIS, console con PIN e risposta reale `SIS bridge: PONG` dal JAR MIDP via loopback. Aprirlo una seconda volta genera `Bridge error: -14` (`KErrInUse`): usare la prima istanza, non reinstallare per questo. Altre funzioni oltre PING non sono supportate.
- Il protocollo consente **solo PING**: niente file, password, shell o privilegi. Il PIN del prototipo non proviene da CSPRNG; **non usarlo come autenticazione sicura**. Servono hardening, timeout/anti-DoS, controlli sui percorsi e consenso esplicito prima di aggiungere import Nokia.

## Toolchain Nokia e SISX sperimentali

[**SYMBIAN_TOOLCHAIN_IT.md**](SYMBIAN_TOOLCHAIN_IT.md) contiene URL, SHA-256, licenza/EULA Nokia, prerequisiti Debian 13, patch GnuPoc/OpenSSL e comandi per ricreare la toolchain. Dopo lettura e accettazione personale della licenza SDK, seguire i comandi nel documento: usare `SYMBIAN_TOOLCHAINS=$HOME/build/e63-local` (escluso dallo snapshot), poi `tools/bootstrap_symbian_fp1.sh` e `tools/build_symbian_fp1.sh`; non estrarre ~1,5 GiB nel progetto. I SISX autofirmati finiscono in `build/symbian/`; la chiave privata di test è esclusa dall’archivio. `tools/verify_symbian_sis.py` controlla byte per byte i payload e la dichiarazione `TargetDevices` nel SISX; il pack grafico `symbian/resources/e63assets.bin` deriva da 11 PNG J2ME dell’APK e 6.264 glifi DejaVu. **Il SISX UI non equivale a un Android 4.2 completo. La 0.2.1 si avvia e mostra Home/Fn sul Nokia; il fix D-pad/softkey della 0.2.2 non è ancora verificato sul telefono.** La toolchain Nokia, ~1,4 GiB, è esterna al progetto e potrebbe non sopravvivere agli snapshot.

## Provare sul PC

Richiede **Python 3.10+**, **Pillow**, JDK (`java`, `keytool`, `jarsigner`) per ricostruire gli APK e GCC per testare il protocollo C. I sei APK e il DEX precompilato sono già inclusi:

```bash
cd /home/user/DalvikE63
python3 -m unittest discover -s tests -v    # qui: 143 test PC, 3 saltati (build/ assente)
python3 tools/probe_midp.py --seconds 4       # JDK + MicroEmulator JAR esterno
python3 tools/capture_android42.py           # nove PNG guest DEX in un'anteprima
python3 tools/capture_native_drawer.py       # parità pixel del corpo drawer C99/Python
python3 tools/capture_rgb565_drawer.py       # crop storico RGB565 C99
python3 tools/capture_rgb565_full.py         # quattro frame PC interi, parità RGB565
python3 web_preview.py --port 8765 --state ./state
# Aprire http://localhost:8765/ e attendere ~2 secondi per il boot.
# Frecce su/giù, Invio/OK, Esc/Indietro, H/Home; 1/App,
# 3/Notifiche, 7/Impostazioni rapide, 9/Widgets nel drawer; oppure click.
```

Percorso dimostrato: **Settings → Wi-Fi ON → Store/login → scheda File Manager → INSTALL (attendere ~4 s) → OPEN → Android/data → errore SystemUI**. L'installazione viene completata dal guest `tickLoop` e passa al `PackageInstaller.apk` nella VFS PC. Per i comandi VFS precedenti: `python3 shell.py --state ./state --import-root ./imports`. Il preview precedente resta avviabile con `python3 adapter_preview.py`, ma non prova l'esecuzione UI J2ME.

Per ricostruire:

```bash
python3 build.py
python3 -m unittest discover -s tests -v
# Esempi C99: eventi, drawer storico e 7 frame completi PC;
# NON fanno startApp né provano la UI sul Nokia:
mkdir -p build
gcc -std=c99 -O2 -Wall -Wextra -Werror -pedantic \
  symbian/runtime/dex_preflight.c symbian/runtime/ui_event_vm.c \
  symbian/runtime/ui_event_cli.c -o build/e63_ui_event_check
build/e63_ui_event_check j2me/classes.dex
gcc -std=c99 -O1 -g -Wall -Wextra -Werror -pedantic \
  -fno-omit-frame-pointer -fsanitize=address,undefined \
  symbian/runtime/dex_preflight.c symbian/runtime/ui_event_vm.c \
  symbian/runtime/ui_paint_cli.c -o build/e63_ui_paint_check
build/e63_ui_paint_check j2me/classes.dex   # drawer guest Apps/Widgets; no PNG C standalone
gcc -std=c99 -O2 -Wall -Wextra -Werror -pedantic \
  symbian/runtime/rgb565_painter.c symbian/runtime/rgb565_cli.c \
  -o build/e63_rgb565_check
build/e63_rgb565_check                    # pixel/rollback + finto present_frame PC
gcc -std=c99 -O1 -g -Wall -Wextra -Werror -pedantic \
  -fno-omit-frame-pointer -fsanitize=address,undefined \
  symbian/runtime/dex_preflight.c symbian/runtime/ui_event_vm.c \
  symbian/runtime/rgb565_painter.c symbian/runtime/ui_full_frame_cli.c \
  -o build/e63_ui_full_frame_check
build/e63_ui_full_frame_check j2me/classes.dex # 7 frame + 3 input, risorse segnaposto
python3 package.py                           # archivio storico PC, senza build/debug.jks
# Lo script tools/package_symbian_release.py è CONGELATO per la release 0.2.1.
# Non eseguirlo per la prova UI 0.2.2: vedere release/LEGGIMI_CONSEGNA_E63.md
```

Il D8 binario ufficiale **8.0.40** è necessario per **riconvertire Java ME modificato**; se non presente, `build.py` usa `j2me/classes.dex` precompilato **solo dopo la verifica degli hash dei `.class` e della provenienza**. `python3 tools/get_d8.py` scarica su richiesta il **solo build tool binario** dal repository Google Maven (SHA-256 fissato nello script), non sorgenti AOSP, e lo mette in `build/tools/` fuori dall'archivio. Per modificare i sorgenti MIDP servono inoltre `ecj.jar`, `proguard.jar`, `cldc.jar`, `midp.jar` di una toolchain MIDP 2.0/CLDC 1.1 esterna; impostare `MIDP_TOOLCHAIN` e usare `j2me/build_j2me.sh` prima di `build.py`. La firma v1 è **debug**, non un certificato fidato di produzione.

Le verifiche storiche di UI J2ME, raster C99 e bridge sono descritte in [FEDELTA_ANDROID42_IT.md](FEDELTA_ANDROID42_IT.md) e [PORTING_E63_STATO.md](PORTING_E63_STATO.md). La suite senza i tool temporanei conta **143 test (3 saltati)**; dopo il bootstrap delle dipendenze ne erano stati eseguiti **153 (1 saltato)**. In entrambi i casi, i test PC e la cross-build non dimostrano Android 4.2 né il funzionamento del nuovo SISX sul Nokia. Le risorse WAV preesistenti restano parte del progetto storico: verificarne i **diritti di redistribuzione** prima di pubblicare nuove copie.

### Quale emulatore per il JAR/SIS?

Il **JAR MIDP 2.0/CLDC 1.1** è stato avviato con **MicroEmulator 2.0.4 headless** sul PC tramite JAD: log osservati di `E63Midlet`, `E63Canvas`, `StoreState` e `E63Midlet$1`; arresto automatico dopo 4 s perché la MIDlet resta attiva. **Non** è una prova grafica, S60v3, socket/SIS o telefono. Le [istruzioni ufficiali EKA2L1 per J2ME](https://eka2l1.github.io/quickstart/j2me/) limitano l'installazione JAR a **S60v1/MIDP 1.0**: non usarla per validare questo JAR su E63/S60v3. EKA2L1 potrà eventualmente verificare i **SISX compilati qui** solo con [firmware S60v3 compatibile acquisito lecitamente](https://eka2l1.github.io/quickstart/basic/installdevice/); non è stato provato nessun SISX nell’emulatore; sul Nokia il **bridge** ha dato PONG e la UI 0.2.1 Home/Fn funziona; l’input 0.2.2 resta da verificare. Si vedano matrice ed evidenze in [PORTING_E63_STATO.md](PORTING_E63_STATO.md).

**Per l’E63 restano:** provare sul **telefono fisico il nuovo SISX UI 0.2.2**, in particolare il softkey sinistro Indietro e il D-pad, e misurare fedeltà di font/bitmap e memoria; il **launcher del bridge e `SocketConnection` hanno già dato un PONG reale**. Poi completare `E63Midlet.startApp`, *tutti* i percorsi di `Canvas.paint`, Forms ed editing nativi, pacchetti/INSTALL→OPEN sul Nokia, VFS/RAM `RFs`/import C: sicuro e firma/trust APK. L’host S60 disegna **sette** schermate guest DEX e riceve tasti, ora/risorse, ma non offre ancora queste funzioni. Un compilato GCCE non prova l’installazione o l’esecuzione su E63.
