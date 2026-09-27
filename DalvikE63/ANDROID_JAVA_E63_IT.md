# Sei APK Android in Java + interprete DEX per E63: stato reale

## Ultima release: build 0.2 di prova, **non beta/Android completo**

**Aggiornamento successivo a questa release storica:** [RUNTIME_NATIVO_E63_IT.md](RUNTIME_NATIVO_E63_IT.md) registra i **dieci JAR DEX AOSP** compilati da sorgenti (solo `frameworks/base` + 21 dipendenze), 11.730 classi, una prima esecuzione C99 di metodi del vero framework su PC e un SISX **esclusivamente diagnostico** in `build/`. `/system` guest è persistente C: read-only. **Non** c'è ancora Activity/UI Android vera, VM completa, release Android o prova hardware del nuovo diagnostico. Il [primo tentativo precedente](FRAMEWORK42_AGGANCIO_IT.md), i suoi 102 test e le sue dichiarazioni «JAR assenti» sono conservati per cronologia, non lo stato attuale.

La [**nuova nota di consegna 0.2**](release/LEGGIMI_E63_ANDROID_JAVA_0.2.md) e il [**SISX 0.2**](release/e63android-0.2-activity-unicode-services-test.sisx) descrivono ciò che è stato effettivamente aggiunto: esecuzione del bytecode DEX di **Main/GuestActivity** nel target Symbian (onCreate/onStart/onResume/onPause/onStop/onDestroy, scelta/comando), parser DEX Unicode Modified UTF-8 con lunghezza UTF-16 e coppie surrogate, rendering UTF-16 Avkon e servizio `RFs` limitato a una **directory privata C:** più import esplicito da due cartelle pubbliche. `INSTALL / ENABLE` abilita soltanto il FileManager pre-incluso dopo doppia conferma; **non installa Android**. Sei APK e SISX sono stati ricostruiti e verificati sul PC (**97 test OK**); **nessun avvio su Nokia E63, nessuna prova Android/emulatore, nessun framework 4.2 completo**. Snapshot dopo eliminazione autorizzata dello ZIP storico: ~111 MiB (non più 126 MiB). Le chiavi e l'SDK restano in `build/` escluso.

**Il resto di questo documento è un resoconto STORICO della 0.1, conservato per la sua release SISX originale.** Affermazioni in basso come «esegue solo Program», «INSTALL sempre negato», «nessun RFs» e «92 test» riguardano **la 0.1**, non la nuova build 0.2. Per lo stato corrente utilizzare la nota 0.2 sopra.

## Archivio storico: build 0.1 (non descrive il SISX 0.2)

**27 settembre 2026.** Questa è una **nuova linea distinta** dai sei APK J2ME in `apks/` e dalle release Nokia in `release/`. Il codice sorgente Java è in `android_java/src/org/e63/dalvik/`; gli APK risultanti sono in [`apks_android/`](apks_android/). **Non** è un formato intermedio compilato in anticipo né un ZIP/JAR rinominato: `javac` compila `Main extends GuestActivity extends android.app.Activity` e un `Program` **diverso per app**; D8 produce il vero `classes.dex` di ciascun APK, aapt ne prepara manifest binario/risorse API 17 e la build lo firma v1 con una chiave **debug**. L’Activity usa widget e servizi del framework Android tramite `Host.java`; ogni `Program` sceglie titolo, testo, immagini proprie, opzioni e reazioni ai comandi. La UI precedente MIDP è **preservata** nelle sue vecchie consegne, non è la UI dei nuovi APK.

| APK Java Android | Asset propri inclusi in `assets/` | Ruolo |
|---|---|---|
| `Launcher.apk` | `wall.png` | Home, scelte per Store, Settings e SystemUI |
| `Settings.apk` | `settings.png` | Wi-Fi/orologio **solo simulati**, non comandi della radio Nokia |
| `Store.apk` | `store.png`, `banner.png` | Catalogo e ricerca offline |
| `SystemUI.apk` | `warning.png`, `lowbattery.wav` | Dialogo di crash **simulato**, nessun servizio SystemUI privilegiato |
| `PackageInstaller.apk` | `files.png`, `packages/FileManager.apk` | Su Android avvia l’installer di sistema con consenso, non installa in silenzio |
| `FileManager.apk` | `files.png`, `lowbattery.wav`, `music.wav` | API di file in `/sdcard` su Android; import solo dalla directory privata dell’app |

Gli asset **non** sono replicati tutti in ogni APK: il manifest `assets/e63-assets.json` registra dimensione e SHA-256 dei soli file di quel pacchetto; `PackageInstaller.apk` contiene proprio il **FileManager.apk firmato**. Ogni APK ha icona, etichetta e Activity rilevate da `aapt dump badging`. Il tema API 17 è Holo scuro, ispirato ad Android 4.2, ma **non** è una replica completa/pixel-identica di Android 4.2 o della precedente Canvas J2ME. Le autorizzazioni Android per storage sono richieste soltanto da Files e Installer. `Host.install` copia l’APK nella cache esterna privata e lancia `ACTION_VIEW` con MIME dell’installer; restituisce 0 finché Android non segnala effettivamente l’app installata. Il file manager Android opera solo nella memoria esterna consentita; import arbitrario da Nokia C: non esiste.

## Che cosa viene davvero eseguito su PC

- `android_shell.py` carica i sei APK firmati, controlla la firma v1 con `jarsigner`, confronta manifest, SHA-256 DEX/asset con `catalog.json`, ed esegue il bytecode **reale** di `Program.onStart/onSelect/onCommand` nell’interprete Python `dalvik/vm.py`. `Host` è un insieme ristretto di servizi/VFS PC: *non* esegue il bytecode del framework Android. Nella sandbox **PC** sono stati osservati Store → PackageInstaller → INSTALL → OPEN → Files e CRUD/import entro `--import-root`; non sono test sul Nokia.
- `symbian/runtime/apk_dex_loader.c` legge **direttamente l’APK ZIP completo** e apre il suo DEX primario STORED, limitando dimensioni/entry, verificando CRC e preflight DEX. `apk_java_vm.c` interpreta un sottoinsieme verificato di opcode D8, registri e salti con budget, delegando **solo** le firme Java esplicite di `Host`. Bytecode non supportato fallisce chiuso: non viene sostituito da schermate hardcoded. La vecchia VM `ui_event_vm.c` per la UI J2ME rimane indipendente.
- La nuova via C99 `apk_java_runtime.c` calcola SHA-256 **di tutti i byte dell’APK** e ammette solo le **sei build esatte** in `symbian/android_java_app/apk_pins.h`, generate insieme agli APK. Non equivale a verificare la firma v1 Android per app esterne; rifiuta APK modificati o ricompilati senza rigenerare/ricompilare i pin. `apk_android_bridge.c` raccoglie righe, pulsanti e richieste d’immagine dal **DEX di quel pacchetto**, verifica l’ownership degli asset e instrada chiamate di storage/path attraverso la whitelist; nessun backend può dichiarare INSTALL riuscita senza conferma. La CLI PC `apk_android_cli.c` usa un backend **di test** che rifiuta installazione, file/audio.
- Per l’anteprima E63, `tools/make_android_java_images.py` estrae **soltanto i PNG di proprietà** dagli APK firmati, verifica i loro hash e genera `symbian/android_java_app/images565.bin` RGB565 (~213 KiB). Il lettore C99 `apk_image_pack.c` ne valida l’hash compilato e distingue `(package, asset)`: un’immagine di SystemUI non si può richiedere dal Launcher. Non è un decoder PNG dinamico sul Nokia.

**Test PC eseguiti:** `python3 -m unittest discover -s tests -q` → **92 test OK** (il test aggiunto ispeziona anche il SISX prodotto e ne confronta i dieci payload); inclusi compilazione separata e ricompilazione deterministica dei DEX Java, `aapt`, `jarsigner`, flussi delle sei app, mutazione di un literal DEX che altera l’output, malformazioni/firme/asset, VM C99 `gcc -std=c99 -Wall -Wextra -Werror -pedantic`, hash su tutto l’APK, ricerca/navigazione C99, rifiuto di installazione fittizia e pack RGB565 riproducibile. Si tratta di prove **PC**, non di Android/E63 reali. Per ripetere:

```bash
cd DalvikE63
# Servono JDK, aapt, D8 binario e android.jar binario API 17:
python3 tools/get_d8.py
python3 tools/get_android_api17.py
python3 tools/build_android_java_apks.py
python3 -m unittest tests.test_android_java_apks -v
python3 android_shell.py  # CLI con servizi PC, non schermata Android
```

Per la sola **build storica 0.1** la build Java richiedeva anche Pillow per le thumbnail native; i soli tool Android allora acquisiti erano i **binari** D8/API 17 in `build/tools/` esclusa dallo snapshot: **in quella fase** non erano state scaricate/clonate sorgenti AOSP. Nel lavoro successivo e separato sono stati autorizzati il repository completo `frameworks/base` e 14 specifiche dipendenze, come descritto sopra. Gli APK possono essere proposti all’installazione Android, ma senza un dispositivo/emulatore Android disponibile **non è stata verificata** l’esecuzione su Android 4.2 o versioni recenti. La firma debug non è una firma di produzione; per installare l’APK FileManager su Android 4.2 l’utente deve confermare il prompt di sistema.

## Percorso Symbian crosscompilato: **prova hardware ancora aperta**

Dopo l’**accettazione personale della licenza Nokia da parte dell’utente**, l’SDK S60 3rd FP1, GnuPoc e GCCE sono stati reinstallati **temporaneamente sotto `build/e63-local/`**, fuori dallo snapshot. `bash tools/build_symbian_java_apks.sh` ha **compilato** `e63android.exe` per ARM/GCCE UREL, generato le risorse AppArc e **firmato con un certificato locale di test** il pacchetto [**`release/e63android-0.1-java-apk-preview.sisx`**](release/e63android-0.1-java-apk-preview.sisx). Questo è un SISX Symbian **separato** dal vecchio `e63os`/bridge: UID/SID `0xE0B63E04`, capability `NONE`, dipendenza installer S60 FP1 `0x102032BE`. L’estrattore `tools/verify_symbian_sis.py` ha confrontato **byte per byte dieci payload**: EXE ARM (45.056 B), due risorse, **i sei APK completi** nell’area privata C: e il pack RGB565 (217.844 B). `elftran -dump s` conferma SID e zero capability; `signsis -o` legge il certificato test autofirmato. Questo prova una **cross-build e un packaging coerenti**, non avvio, risposta dei tasti o prestazioni sul Nokia.

| Nuovo SISX | Byte | SHA-256 | Certificato test (SHA-256) |
|---|---:|---|---|
| `release/e63android-0.1-java-apk-preview.sisx` | **6.843.960** | `21dba7be85b6f662328d0e7b16727df2044498e9a746eaebdacf7073ffab8977` | `AE:C2:64:51:2A:B8:DA:EE:82:61:4B:9A:2A:C1:10:C1:7F:ED:D3:A8:DB:AB:EF:9C:65:5F:61:18:B6:8A:03:F9` |

Il certificato locale è valido **27 settembre 2026 15:14:53 UTC → 26 settembre 2028 15:14:53 UTC**, non è una credenziale di produzione; chiave privata esclusivamente in `build/symbian_java/private/`. `symbian/android_java_app/e63android_app.cpp` legge da C: **i sei interi APK** inclusi nel `.pkg`, controlla i pin SHA-256, esegue i loro metodi Java `Program` con l’interprete C99 e disegna le righe/thumbnail RGB565 di asset dell’APK attivo. Le scelte sono passate al DEX; il **softkey fisico sinistro** è Back, la freccia sinistra del D-pad non lo sostituisce. Nessuno dei precedenti SISX, JAR e APK J2ME è stato sostituito.

Per riprodurre una nuova build su Linux dopo revisione/accettazione personale della EULA Nokia, vedere [toolchain e limiti](SYMBIAN_TOOLCHAIN_IT.md): `SYMBIAN_TOOLCHAINS` deve puntare a una SDK FP1 installata, poi `bash tools/build_symbian_java_apks.sh`. Lo script mette il **nuovo output solo in `build/symbian_java/`**, non sovrascrive la release; verificare i payload prima di copiarlo in `release/`. Una ricompilazione/firma dei sei APK può cambiare i byte: i pin e il SISX devono essere rigenerati insieme. Il test della release nella suite completa rileva APK non più identici; lo script di build omette temporaneamente **quel singolo test**, non i test di APK/interprete, finché non viene aggiornata la release.

I limiti Symbian restano sostanziali: la nuova UI è nativa a righe, **non** interpreta `android.app.Activity` né implementa Android 4.2 completo, decoding PNG dinamico, permessi Android, root Android in RAM o un package manager vero. Lo stato Settings è solo **in memoria**, non Wi-Fi/orologio del telefono. INSTALL su E63 fallisce esplicitamente; FileManager non viene dichiarato installato e non accede ai file Nokia: `RFs` legge solo gli APK e il pack in C: privata. Il bridge MIDP↔SIS precedente resta PING. Servono backend con consenso, verifica delle firme per aggiornamenti non pinnati e implementazione file prima di parlare di installazione Android o import da Nokia. **Nessuna prova del nuovo SISX su E63 fisico né su Android reale:** il comportamento sul telefono resta sconosciuto. Le osservazioni hardware precedenti riguardano soltanto bridge PONG e Home/Fn della vecchia UI 0.2.1; il fix 0.2.2 Back/D-pad non è ancora stato provato.

### Storage/snapshot

Gli APK Android Java pesano complessivamente **6,67 MiB**, il pack RGB565 217.844 B, il nuovo SISX circa **6,53 MiB**. Snapshot condiviso (escludendo `build/`/cache): **~126,0 MiB**, sotto il limite operativo ~128 MiB con margine ridotto. Evitare copie degli APK o del SISX: il `.pkg` li referenzia nei percorsi correnti. SDK Nokia/ZIP grande stanno in `build/` esclusa dallo snapshot e non vengono redistribuiti; i due archivi piccoli GnuPoc/GCCE precedenti restano in `~/toolchains/gnupoc-downloads/`.
