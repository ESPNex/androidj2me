# Struttura del precedente OS J2ME/DEX per E63 — VM C99 e SISX

**Aggiornamento non rilasciato:** [stato nativo AOSP 4.2.2](RUNTIME_NATIVO_E63_IT.md): 10 JAR boot e risorse compilati da AOSP, indice on-disk 11.730 classi, verifica SHA a blocchi su C: e primo sottoinsieme di metodi DEX interi eseguiti nativamente su PC. Un SISX **diagnostico** con gli archivi è in `build/` e non è mai stato provato sull'E63; manca Activity/UI Android completa. Il [primo aggancio](FRAMEWORK42_AGGANCIO_IT.md) e la tabella sotto sono storici. La 0.2 resta l'ultima build consegnata.

**Architettura Java della build consegnata 0.2:** [nota di consegna e limiti](release/LEGGIMI_E63_ANDROID_JAVA_0.2.md): metodi reali `Main/GuestActivity` DEX e parser Unicode, ma soltanto shim Activity/Host, non framework Android 4.2 completo né beta. La cross-build ARM non è una prova hardware. Il testo sottostante rimane dedicato alla precedente UI J2ME. [Panoramica Java](ANDROID_JAVA_E63_IT.md). Le affermazioni sotto descrivono la **release precedente basata su UI J2ME**, non i nuovi APK; non considerare i vecchi SISX una prova dei nuovi APK su E63.

**Obiettivo storico:** mantenere `E63Midlet`/`E63Canvas` convertiti in DEX come **unica sorgente delle schermate e delle decisioni dell’interfaccia**, con look Jelly Bean 4.2 descritto in [FEDELTA_ANDROID42_IT.md](FEDELTA_ANDROID42_IT.md). Symbian fornisce primitive (schermo, input, RMS, socket, APK/file system), non ridisegna Home, Store o File Manager. La UI **completa** resta nel runtime Python PC. Il **sottoinsieme nativo** `ui_event_vm.c` interpreta gli eventi e `Canvas.paint(Graphics)` originali per sette schermate guest: Home, cartella vuota, spegnimento, drawer, notifiche, Quick Settings e Recenti, con status/nav; esegue `clock()`, `batteryPercent()` e `<clinit>` dei glifi dal vero DEX. `rgb565_painter.c` rasterizza frame interi C99. **20** confronti RGB565 PC 320×240/220×180 coincidono con Python; altri **10** a 320×240 usano proprio il pack PNG/font inserito nel SISX. Ora l’host Avkon `symbian/e63os_app.cpp` e il server TCP/launcher sono **compilati ARM/GCCE in due SISX autofirmati**, con contenuto verificato, con risultati **distinti** sull’E63: il **bridge SIS avvia la console e risponde PONG al JAR MIDP via TCP loopback**; la **UI grafica 0.2.1** mostra Home e risponde a Fn+numeri sul Nokia, ma D-pad e softkey sinistro non erano funzionali. La **0.2.2** crosscompilata aggiunge i servizi DEX per Back/pad e resta da provare sul telefono. Mancano `startApp`, le altre schermate C99, Forms, integrazione VFS C99 con `RFs` e un OS Android completo sul telefono. [Build, font, licenza e limiti](SYMBIAN_TOOLCHAIN_IT.md).

## Confini e flusso

```text
       Nokia E63: 0.2.1 HOME + Fn OSSERVATI         PC: ESEGUITO/TESTATO
 tasti/softkey -> e63os_app.cpp                  web_preview.py
                  |                                    |
                  v                                    v
      ui_event_vm.c -> Canvas.paint DEX       JavaMEUI + dex_ops + J2MEDex
              |   (sette path)                         | (UI completa)
              v                                        v
      rgb565_painter.c -> CFbsBitmap           MIDPHost/Pillow -> PNG
              |                                    |
              +-- pack SISX PNG/glifi            +-- PNG/font/clock da APK
              +-- clock locale, battery '?'      +-- VFS RAM + state/c_drive
              +-- presentazione Window Server
                        (Home 0.2.1 vista sull’E63)

 MIDP SocketConnection -- loopback 127.0.0.1:27463 -- e63bridge.exe
                                       (RSocket su E63: PIN + PONG provati)

  Mancano startApp, altri paint, Forms, VFS C99<->RFs C:,
  file/import reali, installatore su E63 e verifica/trust APK.
```

**La divisione già operativa sul PC:** `JavaMEUI.tick()` esegue `StoreState.finishInstall()` nel **DEX originale**; soltanto dopo domanda a `PackageService` di installare FileManager. `dalvik/os_services.py` definisce il contratto, `dalvik/pc_services.py` lo implementa invocando il DEX di `PackageInstaller.apk`; un backend non disponibile rifiuta l’installazione. Se il commit fallisce, il runtime azzera il flag RMS *installato* e ripristina un `StoreState` non installato: non mostra un falso OPEN permanente. Test con backend fittizio e APK installer manomesso. La UI non importa più direttamente `DesktopShell`.

**Il primo nucleo nativo:** `symbian/runtime/dex_preflight.[ch]` valida il `dex\n035` reale, sezioni, stringhe, class data, offset di codice e Adler32 (massimo 32 MiB), distinguendo 9 classi e 118 metodi con codice. `dex_vm.[ch]` risolve metodo **con prototipo esatto** e interpreta gli opcode effettivi di `StoreState`: costruttore, `activate`, `finishInstall`, `isInstalled` e `isInstalling`. I campi sono indicizzati dagli ID del DEX, non da copie delle regole J2ME; una mutazione `if-eqz`→`if-nez` cambia il risultato anche nel C. Validazione di salti, registri e target, limite di istruzioni, rollback dei campi in caso di **errore dell’interprete** e rifiuto esplicito di opcode/chiamate non supportati. Questo rollback protettivo non pretende di riprodurre la semantica completa delle eccezioni Java. `vm_cli.c` è solo una dimostrazione GCC host. Mancano heap di oggetti generale, eccezioni guest, LCDUI e rendering del Canvas.

**Seconda tappa C99, eventi della UI originale:** `symbian/runtime/ui_event_vm.[ch]` usa il DEX convertito già verificato dal preflight; risolve field/method ID originali, tiene oggetti/array/stringhe con limiti espliciti (32 oggetti, 16 array da 32 elementi, 64 stringhe ASCII temporanee), interpreta invoke guest, field/array, branch e switch con budget di passi e limite di profondità. Fornisce al codice guest solo primitive MIDP circoscritte: dimensioni del Canvas, lookup del `getGameAction` tramite callback e un bit di `repaint` da consumare in futuro. Su GCC, `E63Canvas.keyPressed(53/56)` fa **BOOT → HOME → focus Settings → SETTINGS** eseguendo davvero `E63Midlet.activate/move/listCount/navigate` e `StoreState.isInstalled`; `pointerPressed(160,220)` esegue **SETTINGS → HOME**. Anche `keyPressed(49/51/55)` apre il drawer, le notifiche o Quick Settings nel DEX, con parità dei campi fra VM C99 e Python; e sette percorsi di `Canvas.paint` dipingono **l'intero frame** nel C99 PC, compresi drawer, notifiche, Quick Settings, Home e le barre guest. Notifiche lifecycle `hideNotify/showNotify` e tasti ripetuti sono anch'essi DEX guest. `ui_event_cli.c` semina i riferimenti iniziali a Midlet/Canvas/Store/array **senza eseguire `startApp`**; non sono schermate host codificate a mano. Una mutazione del `classes.dex` originale cambia il conteggio nativo; eventi/campi vengono confrontati con la VM Python e il codice C è stato eseguito con AddressSanitizer/UBSan e 120 mutazioni limitate. Errore interprete: rollback degli oggetti, array e redraw pending, **non** semantica generale delle eccezioni Java. Tra i percorsi PC verificati c’è ora Back `-6` da Quick Settings e il pad direzionale; stringhe Unicode/Forms, **le altre schermate** di `Canvas.paint` e avvio autonomo restano fuori, così come l’integrazione di questo nucleo con il precedente `dex_vm.c` di StoreState.

**Prima tappa C99 Graphics, corpo app drawer (conservata):** lo stesso `ui_event_vm.[ch]` segue `paintAppDrawer → homeIcon/center/text` e `StoreState.isInstalled` nel `classes.dex` J2ME già convertito: due/tre icone in base al flag guest, selezione dall’array, tab Widgets. L’ABI host accetta soltanto riferimenti tipizzati `Graphics`, `Font`, `Image` (asset ID associati dall’host a immagini dell’APK firmato), metriche font e dimensioni delle immagini **pure**, 256 draw-op al massimo e testi ASCII di 160 byte al massimo. `setColor`, rettangoli, linee, immagini e stringhe finiscono in un buffer; un **unico commit atomico** avviene solo dopo successo del metodo guest, su errore nessun frame parziale. Il test PC usa Pillow soltanto come servizio MIDP: pixel identici nel **crop y=18..h−32** a 320×240 e 220×180, prima/dopo lo stato installed simulato, Apps/Widgets. Il CLI C99 usa metriche fittizie per provare il flusso sotto ASan/UBSan e non scrive un PNG. Una stringa modificata **nel DEX** cambia il disegno C99. Questa prova storica da sola non implicava frame interi; la tappa successiva li verifica su sette schermate. Non implica rasterizer Symbian, verifica firma da parte del preflight né SIS. Vedi [anteprima del corpo drawer](assets/preview_c99_drawer_pc.png).

**Raster portabile (test PC e ora build GCCE per S60):** `symbian/runtime/rgb565_painter.[ch]` applica il buffer Graphics **senza decidere la UI**. Sono implementati nel C99 clipping di rettangoli/linee, stringhe da maschere font, compositing RGBA delle icone, RGB565 riga per riga e doppio buffer: un fault guest o un errore delle callback lascia intatti i pixel pubblicati. I test forniscono tramite callback *soltanto* PNG dell’APK firmato già decodificati e maschere di glifi da Pillow; anche la VM Python usa gli stessi font/asset. Sei crop Apps/Widgets (320×240 e 220×180) sono identici pixel per pixel dopo quantizzazione RGB565; un CLI C99 con asset/glyph sintetici prova il raster senza Python sotto ASan/UBSan. **Porting incrementale successivo:** lo stesso raster accetta `setClip` del viewport, `drawArc` circolare ed esegue dal DEX i glifi batteria inizializzati da `<clinit>`, le stringhe e l'ora da `Calendar` via callback locale. `Canvas.paint` del guest sceglie sette schermate e dipinge **status/nav nel batch atomico**: 20 confronti dei **frame interi** a due risoluzioni coincidono esattamente con Python quantizzato; mutare un byte della matrice glifi **nel DEX** cambia i pixel della batteria. Input guest→paint e rollback/repaint ripetuti sono testati. `ui_full_frame_cli.c` attraversa DEX→raster→**callback fittizio PC** `E63DeviceOps.present_frame` sotto ASan/UBSan con risorse sintetiche. Ora un adapter `e63os_app.cpp` presenta quel RGB565 via `CFbsBitmap`/Window Server e un SISX contiene VM/raster/font/DEX, ma la parità dei pixel è provata solo su PC: Home 0.2.1 e Fn sono osservati sul telefono, mentre il nuovo input 0.2.2 deve ancora essere misurato lì. [Confronto completo](assets/preview_rgb565_full_pc.png) · [crop storico](assets/preview_rgb565_pc.png).

**Confine Symbian parzialmente realizzato:** `symbian/runtime/device_api.h` resta un contratto **più ampio** per framebuffer RGB565, asset MIDP, RMS, clock, TCP loopback, VFS e installazione di FileManager soltanto; non è implementato nella sua interezza. Il nuovo `e63os_app.cpp` implementa direttamente l’adapter Avkon per tasti, file DEX/pack privati C:, maschere e immagini precalcolate, clock e presentazione bitmap; `e63bridge.cpp` fornisce un server RSocket PING separato, **non** callback VFS/UI. `vfs_mount.[ch]` normalizza mount/alias e limiti/ruoli; `vfs_ram.[ch]` custodisce `/tmp`/`/cache` in memoria (32 file, 64 KiB/file, 256 KiB totali). Compilati/testati con GCC PC, i moduli VFS **non sono collegati alla VM C o a RFs**. VM e raster dell’host 0.2.1 sono **avviati sull’E63 per Home/Fn**; il fix 0.2.2 per softkey/pad non è ancora provato lì. Adler32 non autentica il DEX: servono verifica APK/firme e politica di trust.

## Albero delle responsabilità

| Percorso | Responsabilità | Stato |
|---|---|---|
| `j2me/src/.../{E63Midlet,E63Canvas,StoreState,BridgeClient}.java` | UI, navigazione, INSTALL → OPEN e client PING **originali** | Sorgenti/JAR/DEX convertiti |
| `apks/Launcher.apk` | Entry `E63Midlet`, risorse e DEX J2ME firmati debug | Eseguito su PC, non su Android/E63 |
| `apks/{Settings,Store,SystemUI,PackageInstaller,FileManager}.apk` | APK contenenti lo stesso DEX J2ME e adattatori di servizio | VFS PC; non app Android 4.2 autonome |
| `dalvik/{dex_j2me,dex_ops,ui_vm}.py` | Decoder/interprete della UI originale | Funzionante su PC, **non** portato in C++ |
| `dalvik/midp_host.py` | Shim MIDP + Pillow, RMS persistente nell'analogia `state/c_drive`, socket loopback | Funzionante su PC, **non** portato |
| `dalvik/{os_services,pc_services}.py` | Contratto del package service e backend PC | Funzionante, testabile con backend sostitutivo |
| `dalvik/vfs.py`, `dalvik/host.py`, `shell.py` | Namespace RAM/`/system` read-only, analogia C: PC, firma debug e DEX ausiliario PackageInstaller | Solo sandbox PC; nulla è montato sul Nokia |
| `symbian/runtime/dex_preflight.[ch]` | Parsing e validazione DEX-035 C99, risoluzione metodo/prototipo | Compilato/testato con GCC PC; non verifica firma APK |
| `symbian/runtime/dex_vm.[ch]`, `vm_cli.c` | **Esecuzione DEX C99 parziale** del vero StoreState | GCC PC, parità con VM Python; questo modulo non disegna Canvas |
| `symbian/runtime/ui_event_vm.[ch]`, `{ui_event,ui_paint,ui_full_frame}_cli.c` | Eventi guest e **Canvas.paint** DEX C99 per sette schermate; comandi MIDP, stato guest e glifi batteria dal DEX | GCC PC + GCCE ARM; 20 frame PC interi pixel-identici; non `startApp` o tutti i path |
| `symbian/runtime/rgb565_painter.[ch]`, `rgb565_cli.c` | Compositing RGB565 C99: asset/glifo da callback, lente circolare, commit atomico | GCC PC/ASan + GCCE ARM; Home 0.2.1 osservata su E63, parità pixel solo PC |
| `symbian/e63os_app.cpp`, `symbian/resources/e63assets.bin` | Adapter Avkon/Window Server con bitmap 320×240, tasti, asset PNG/font precalcolati da APK e DEX guest originale | GCCE SISX: 10 frame pack/guest identici **solo su PC**; Home/Fn 0.2.1 su E63, softkey/pad 0.2.2 non ancora provati |
| `symbian/runtime/{vfs_mount,vfs_ram}.[ch]` | Routing mount/permessi e dati volatili con budget RAM C99 | Compilati/testati GCC PC; **non** nel SIS UI né collegati a `RFs` |
| `symbian/runtime/device_api.h` | ABI prevista per display, keycode→MIDP, RFs/RSocket | Adapter grafico nativo implementato separatamente; contratto completo **non** realizzato |
| `symbian/e63bridge.cpp`, `symbian/bridge_protocol.c`, `symbian/e63bridge_launch.cpp` | Server loopback TCP PING e launcher AppArc nel menu | **E63 fisico: launcher + console con PIN, JAR MIDP riceve `SIS bridge: PONG`**; apertura duplicata `-14`. Non esegue file API/OS completo |

## Storage: cosa esiste oggi e cosa manca

| Percorso virtuale | Backend PC attuale | Nucleo C99 | Backend Nokia E63 |
|---|---|---|---|
| `/`, `/tmp`, `/cache` | Namespace Python in RAM; file temporanei max 1 MiB ciascuno, 8 MiB complessivi; persi al riavvio | Mount statici e file RAM, 32 file/64 KiB per file/256 KiB totali | **Manca** il collegamento al ciclo vita del SIS |
| `/system/app`, `/system/media` | Vista sola lettura degli APK firmati del bundle; piccolo WAV caricato in memoria, APK non copiati in RAM | Router di percorsi autorizzati, **nessun lettore bundle** | Pack statico SISX letto direttamente per font/PNG DEX UI; **mancano** vista `/system`/APK on-demand e verifica firma/trust |
| `/data/app`, `/data/data`, RMS, flags | `state/c_drive/private/e63os/data`, `.../rms`, `.../settings` sul PC | Route `C_PRIVATE`, **nessun I/O** | Host `RFs` apre i **soli** `classes.dex`/`e63assets.bin` privati; nessun RMS/dato Android guest su C: |
| `/sdcard`, `/storage/emulated/{0,legacy}`, `/data/media/0` | `state/c_drive/media/0` sul PC; scritture FileManager su alias ammessi | Route `C_MEDIA`, alias `/data/media/0` sola lettura, **nessun I/O** | **Mancano** mappatura C:, consenso/import utente e capability |

Il primo avvio PC migra `state/rootfs/data` (incluse app e media), `state/flags.json` e `state/j2me_rms.json` nei nuovi percorsi. **Fare backup dello stato**; se coesistono vecchi e nuovi dati il servizio rifiuta la migrazione e richiede una risoluzione manuale, senza sovrascrivere i file. `state/rootfs/system` residua non è più usata, non viene rimossa automaticamente. `--import-root` copia solo file autorizzati nella sandbox PC e **non** accede al Nokia. Il prefisso `c_drive` è una cartella di test, **non** la vera unità `C:` dell'E63.

Destinazione Symbian: i dati privati dovranno stare sotto **`C:\\private\\<UID_OS>\\...`** tramite `RFs` e capability corrette; `/data/media/0` non dà accesso implicito a `C:` arbitraria. Non caricare i ~10 MiB di APK in RAM: leggerli da un bundle verificato on demand. FileManager: la schermata `paintFiles` J2ME è ancora statica. In futuro dovrà invocare API filesystem esplicite soggette a capability e consenso, senza sostituirla con markup o un FileManager hardcoded nell’host.

## Gate di sviluppo prima di parlare di OS sull’E63

1. **Fatto su PC:** preflight e interprete C99 del vero `StoreState` DEX; interprete multi-oggetto C99 su eventi reali e sette `Canvas.paint` guest con confronto input→stato→**20 frame RGB565 interi**, mutazioni DEX, protezioni di tipo/budget/rollback. UI Python/PackageService, VFS RAM + `state/c_drive`, router e dati RAM C99 testati; altre **10** scene VM+raster con le risorse SISX pixel-identiche al guest. Non è test hardware.
2. **Fatto:** SDK S60 3rd FP1, tre EXE GCCE, SISX UI Avkon e bridge/launcher autofirmati; payload SISX verificati e capability E32 controllate. **Sul Nokia E63 l’utente ha verificato** console/PONG del bridge e **Home/Fn della UI 0.2.1**. La UI **0.2.2** ricompilata instrada il softkey sinistro su `keyPressed(-6)`/`E63Midlet.back`, distinto dalla freccia sinistra; il pad usa codici direzionali guest. Questa modifica passa 78 test PC, **non ancora una prova fisica dei tasti**; il PONG non è prova di un OS Android sul telefono.
3. **Da fare:** completare i due nuclei C99 fino a `E63Midlet.startApp` dal DEX e **tutti** i `Canvas.paint` (Settings/Login/Store/Files), Unicode, oggetti/eccezioni, Forms/editing, gestione softkey integrale e servizi MIDP. Non introdurre schermate alternative host quando la VM non esegue il guest.
4. **Da fare:** collegare router/RAM C99 a `RFs`/RMS sul telefono, `/system` APK on-demand, import C: autorizzato, verifica APK/firme e package manager. Il pack font/PNG grafico statico esiste; non equivale a un decoder PNG generale o a una rootfs in RAM sul dispositivo.
5. **Da fare prima di importare C:** consenso esplicito, controllo dei percorsi, autenticazione più forte, limiti di risorse; il PIN PING non è una misura di sicurezza per importazioni.

## Verifica locale

```bash
cd DalvikE63
mkdir -p build
gcc -std=c99 -O2 -Wall -Wextra -Werror -pedantic \
  symbian/runtime/dex_preflight.c symbian/runtime/preflight_cli.c \
  -o build/e63_dex_check
build/e63_dex_check j2me/classes.dex
# dex035 classes=9 method_ids=215 with_code=118 guest_ui=1
gcc -std=c99 -O2 -Wall -Wextra -Werror -pedantic \
  symbian/runtime/dex_preflight.c symbian/runtime/dex_vm.c \
  symbian/runtime/vm_cli.c -o build/e63_vm_check
build/e63_vm_check j2me/classes.dex
# guest StoreState DEX: first=1 waiting=3 after=2 installed=1
gcc -std=c99 -O2 -Wall -Wextra -Werror -pedantic \
  symbian/runtime/dex_preflight.c symbian/runtime/ui_event_vm.c \
  symbian/runtime/ui_event_cli.c -o build/e63_ui_event_check
build/e63_ui_event_check j2me/classes.dex
# original Canvas/Midlet DEX: screen=2 focus_home=1 redraw=1
# original Canvas pointer DEX: home_screen=1
gcc -std=c99 -O1 -g -Wall -Wextra -Werror -pedantic \
  -fno-omit-frame-pointer -fsanitize=address,undefined \
  symbian/runtime/dex_preflight.c symbian/runtime/ui_event_vm.c \
  symbian/runtime/ui_paint_cli.c -o build/e63_ui_paint_check
build/e63_ui_paint_check j2me/classes.dex
# Apps: 22/26 ops prima/dopo installed; Widgets: 13; nessun PNG dal CLI C
gcc -std=c99 -O2 -Wall -Wextra -Werror -pedantic \
  symbian/runtime/rgb565_painter.c symbian/runtime/rgb565_cli.c \
  -o build/e63_rgb565_check
build/e63_rgb565_check # raster C99 + rollback + finto present_frame PC
gcc -std=c99 -O1 -g -Wall -Wextra -Werror -pedantic \
  -fno-omit-frame-pointer -fsanitize=address,undefined \
  symbian/runtime/dex_preflight.c symbian/runtime/ui_event_vm.c \
  symbian/runtime/rgb565_painter.c symbian/runtime/ui_full_frame_cli.c \
  -o build/e63_ui_full_frame_check
build/e63_ui_full_frame_check j2me/classes.dex # 7 scene + 3 input, mock PC
python3 tools/capture_rgb565_drawer.py # crop storico RGB565 C99/Python
python3 tools/capture_rgb565_full.py # frame interi RGB565 C99/Python
gcc -std=c99 -Wall -Wextra -Werror -pedantic -c \
  symbian/runtime/vfs_mount.c -o build/vfs_mount.o
gcc -std=c99 -Wall -Wextra -Werror -pedantic -c \
  symbian/runtime/vfs_ram.c -o build/vfs_ram.o
python3 -m unittest discover -s tests -v   # 92 test PC complessivi; 78 del ramo storico
python3 tools/probe_midp.py --seconds 4       # richiede MicroEmulator esterno
python3 web_preview.py --port 8765 --state ./state
```

I CLI nativi accettano un DEX con checksum corretto, **non** sostituiscono la verifica crittografica dell’APK. `dex_vm.c` esegue **solo il sottoinsieme di StoreState**; `ui_event_vm.c` interpreta anche eventi della Canvas, percorsi Midlet selezionati e `Canvas.paint` su sette schermate, ma richiede stato iniziale seminato (esegue solo il vero `<clinit>` Canvas), non esegue `startApp` o ogni path e non autentica un APK. `rgb565_painter.c` produce pixel RGB565 testati su PC ed è nel SISX GCCE; l’adapter Avkon li mostra via `CFbsBitmap` e la **Home 0.2.1 è stata vista sul telefono**, senza confronto di tutti i pixel. `vfs_mount.c`/`vfs_ram.c` restano moduli separati, non connessi alla UI nativa. La pagina live resta la dimostrazione PC della UI J2ME completa dipinta dal DEX. Restano incompleti `startApp`, le altre schermate guest, file reali e package manager; l’input del **nuovo SISX UI 0.2.2** è compilato/testato su PC ma non provato sull’E63, mentre il **bridge SISX** ha restituito PONG via MIDP sul dispositivo. [Toolchain e firma](SYMBIAN_TOOLCHAIN_IT.md) · [gate hardware](PORTING_E63_STATO.md).
