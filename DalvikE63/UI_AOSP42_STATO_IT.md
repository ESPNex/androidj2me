# UI Android 4.2 AOSP su E63 — avanzamento sperimentale

**27 settembre 2026. Non è una UI Android funzionante.** Aggiornamento: il [nuovo interprete a oggetti DEX autentici](OGGETTI_AOSP42_E63_IT.md) esegue anche `FolderInfo` con due `ArrayList`, `EmptyArray.<clinit>`, `unbind()/clear()` e `size/isEmpty` reali dal DEX core, più `Point.<clinit>`/`Point$1`/`CREATOR`, `Point(240,320)`, `offset` e `hashCode` dal vero `framework.jar`; il SISX diagnostico 0.6 separato ricompilato/verificato (non testato sul Nokia) è documentato lì. Il presente resoconto conserva le prove della **tappa AXML/0.5 precedente**, non sostituisce il nuovo stato. Proseguendo il porting, il ramo nativo ora riconosce le dichiarazioni **Activity/Service e intent-filter autentici** nel `AndroidManifest.xml` binario compilato da AAPT per quattro APK AOSP 4.2.2_r1.2. Rimane distinta la vecchia UI J2ME/Java APK; release 0.2, SISX/JAR originali e sei APK legacy non sono stati sostituiti.

| APK AOSP firmato con chiave *pubblica di sviluppo* | Classe DEX esistente | Manifest compilato e criterio riconosciuto |
|---|---|---|
| `Launcher2.apk` (`com.android.launcher`, 732 classi) | `com.android.launcher2.Launcher` | Activity con `MAIN` e `HOME` **nello stesso** intent-filter; AXML 8.216 byte |
| `AOSP42Settings.apk` (`com.android.settings`, 2.398 classi) | `com.android.settings.Settings` | Activity con `android.settings.SETTINGS` e `LAUNCHER`; AXML 88.820 byte |
| `AOSP42PackageInstaller.apk` (`com.android.packageinstaller`, 348 classi) | `com.android.packageinstaller.PackageInstallerActivity` | Activity con `INSTALL_PACKAGE` e `DEFAULT`; AXML 4.524 byte |
| `AOSP42SystemUI.apk` (`com.android.systemui`, 404 classi) | `com.android.systemui.SystemUIService` | **Service**, non Activity; AXML 14.664 byte |

Le quattro applicazioni usano Java, DEX, risorse e manifest provenienti da sorgenti AOSP autorizzati; le firme v1 impiegano le **chiavi di test AOSP**, non una chiave di produzione fidata dal Nokia. Le dimensioni dei quattro APK firmati restano rispettivamente 16.345.163, 12.726.584, 712.894 e 3.185.430 byte. `/system` guest è **persistente e in sola lettura su C:**: non viene interamente caricato in RAM. Gli indici DEX e i manifest compilati sono piccole cache persistenti sotto `/data/e63-uiindex/` e `/data/e63-uimanifest/`. I 116.224 byte AXML derivano **esattamente** dalle voci ZIP dei quattro APK firmati, con SHA-256 indipendenti in `ui_apk_pins.h`; la procedura di creazione/verifica confronta ogni copia con l'APK originale. Su Nokia il lettore usa `RFile` e richieste di massimo 128 byte per il parsing AXML; SHA-256 e formato sono controllati prima di riconoscere una dichiarazione. L'APK intero è autenticato a blocchi, non caricato in memoria.

## Cosa esiste nel codice e cosa dimostrano le prove

- `symbian/runtime/ui_manifest_axml.[ch]` decodifica la string pool UTF-16, le namespace, gli elementi e gli attributi AAPT entro limiti prefissati; gestisce nomi di classe relativi, distingue Service/Activity, esige una sola dichiarazione e, per le Activity, azione e categoria **nello stesso filtro**. Formati non supportati o dati corrotti falliscono chiusi. Non è un parser di layout/View né un gestore di componenti.
- `E63UiStore::ResolveComponent` valida prima SHA-256 dell'APK, dell'indice e la vera `class_def` nel DEX, poi SHA-256 della cache AXML e il componente nel manifest. Il tasto **4** può diagnosticare il `Launcher2` HOME; se si usa il vecchio diagnostico a 40 payload senza la nuova cache, dichiara esplicitamente **«AXML non confermato, NO UI»** e può mostrare soltanto la classe DEX. Il tasto **0** resta la prova indipendente di `Color.argb` dal DEX framework.
- `E63UiStore::CallStaticInt` riusa l'interprete di metodi primitivi per leggere il **vero DEX firmato di Launcher2**, con nuova autenticazione a blocchi dell'APK prima della chiamata. Il tasto **5** prova `com.android.launcher2.Utilities.roundToPow2(33)`: l'atteso `64` deriva dal bytecode Java AOSP, non da una funzione sostitutiva dell'host. Il metodo package-private è un helper numerico della UI, **non** il suo `onCreate`, non inizializza classi e non mostra schermate. Su PC sono passati casi 1/2/3/4/5/9/16/33, oltre al rifiuto di un metodo inesistente; l'esecuzione su Nokia non è stata provata.
- Cinque test sintetici/di provenienza AXML più sei controlli sugli APK UI reali sono passati sull'**host**, così come quattro regressioni del lettore DEX nativo: **15 test mirati** nel complesso. Le quattro fixture AXML byte-identiche (`tests/fixtures/aosp42_axml/`, 116.224 byte) e i pin rimangono nel progetto anche quando la cartella pesante `build/` viene eliminata dallo snapshot. Nessun risultato prova l'esecuzione su E63.
- È stato ricostruito con GCCE, firmato **localmente** e verificato byte-per-byte un **nuovo SISX diagnostico separato di 44 payload**, con i quattro AXML aggiuntivi oltre ai 40 file del diagnostico UI precedente. Il parser SIS9 verifica i payload e la dipendenza FP1 `0x102032BE`, **non** l'installabilità/avvio sul Nokia. Il SISX a 40 file è stato ricostruito separatamente e usa un EXE differente: non è byte-identico all'artefatto sperimentale 0.4 precedente.

**SISX storico della tappa 0.5, 44 payload (non release; attualmente da ricostruire sotto `build/`):** `build/aosp42-ui-axml-diagnostic/e63android-aosp42-ui-axml-diagnostic.sisx`, 55.350.316 byte, SHA-256 `8e76b907bb6cc2a9f5505849e3103b84f7f565c64f6c225c32a95844acc48a2e`. **SISX storico 0.4, 40 payload (attualmente da ricostruire sotto `build/`):** `build/aosp42-ui-diagnostic/e63android-aosp42-ui-diagnostic.sisx`, 55.329.444 byte, SHA-256 `38273d50dc23f620322bd8dd61c49a3c870d207dc9aade5bc01c6480910e52c1`. Entrambi sono sotto `build/` **non persistente**, non nella cartella `release/`. Condividono l'UID Nokia `0xE0B63E04` con la 0.2: un'installazione volontaria potrebbe aggiornarla/sovrascriverla *sul telefono* e richiede backup, spazio libero sufficiente su C: e accettazione esplicita del rischio. **Non è stato chiesto né effettuato un test sul Nokia.**

## Limite architetturale, senza etichette fuorvianti

**Non si avvia nessuna Activity AOSP e non si mostra nessuna schermata AOSP.** Oltre a un sottoinsieme di metodi statici interi del framework e di un APK UI autenticato, il [nuovo modulo](OGGETTI_AOSP42_E63_IT.md) esegue veri costruttori di dati Launcher2 e `Point` dal framework, legge campi ereditati, invoca `Object.<init>` dal DEX core ed esegue alcune class-init effettive. Mancano ancora heap generale/GC, invocazioni virtuali complete, eccezioni e thread Dalvik, inizializzazione **generale** delle classi, JNI, Binder, PackageManager/ActivityManager/ActivityThread, inflazione delle risorse/layout e rendering delle View tramite Window Server. `Launcher.onCreate` autentico usa tra l'altro `AppWidgetManager`, `setContentView(R.layout.launcher)`, preferenze e loader: non può essere sostituito correttamente da una UI nativa che ne imita lo stile. `SystemUIService` non parte; l'errore SystemUI simulato della vecchia UI resta separato. Non si chiama questo ramo **Android 4.2 completo**, beta, release o prova E63.

Per continuare verso UI reale bisogna ampliare il primo interprete a oggetti per eseguire **molti altri metodi delle vere classi AOSP**, con heap e linking fra i dieci boot JAR e gli APK; implementare i servizi/JNI/Binder richiesti; risolvere `resources.arsc` e i layout binari per `View`/input; poi verificare realmente sull'hardware con backup. Le prime quattro istanze DEX e il manifest autentico non abbreviano magicamente questi passaggi.

## Ricostruzione, se `build/` viene rimossa dallo snapshot

Gli artefatti grandi e l'SDK Nokia con licenza rimangono esclusivamente sotto `build/`; *non* ridistribuire l'SDK o chiavi private di firma locale. I quattro AXML fixture e gli script sono persistenti. Dopo aver acquisito **solo** `frameworks/base` e le dipendenze AOSP autorizzate come in `RUNTIME_NATIVO_E63_IT.md`:

```bash
python3 tools/bootstrap_aosp42_ui.py
python3 tools/build_aosp42_bootclasspath.py --stage
python3 tools/build_aosp42_ui_apks.py
python3 -m unittest tests.test_ui_manifest_axml tests.test_aosp42_ui_apks \
  tests.test_aosp42_native_boot -v
# SDK S60 FP1 installato localmente dopo accettazione personale della EULA:
python3 tools/build_aosp42_ui_axml_diagnostic_sis.py  # default build/toolchains/
```

Per cache AXML da APK firmati **già staged**, senza ricompilare o rifirmare: `python3 tools/build_aosp42_ui_apks.py --manifest-caches-only`. Tutte le prove PC/GCCE restano distinte da una prova sul Nokia E63 fisico.
