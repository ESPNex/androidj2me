# Oggetti AOSP 4.2 nel runtime DEX nativo E63 — stato sperimentale

**27 settembre 2026. Non è Android avviato sul Nokia E63, né una UI Android funzionante.** Il ramo nuovo interpreta alcuni metodi DEX autentici di `Launcher2.apk`, `core.jar` e **`framework.jar`** compilati da AOSP `android-4.2.2_r1.2`. Non sostituisce il porting MIDP, gli APK/JAR/SISX storici o la release 0.2. `/system` guest resta **persistente, read-only su C:**; `/data` e cache stanno prevalentemente su C:, non si carica l'intero `/system` in RAM.

## Bytecode realmente eseguito

| Classe | Operazione DEX autentica osservabile | Limite da non fraintendere |
|---|---|---|
| `Launcher2.ItemInfo` | Costruttore, `Object.<init>` nel DEX di core, campi `id=-1`, `container=-1`, `spanX=1`, `unbind()` | Modello, non `Activity`/`View` |
| `DropTarget$DragObject`, `ApplicationInfo`, `ShortcutInfo` | Costruttori, `invoke-super`, campi ereditati e `unbind()` dove esiste | Non avviano trascinamento o Home Android |
| `LauncherAppWidgetInfo(37, null)` | Argomenti DEX tipizzati, inclusi `I` e riferimento Java null; `ItemInfo.<init>` e `unbind()` | Nessun `AppWidgetHost` né widget grafico |
| `FolderInfo` | Due distinti `new-instance java.util.ArrayList`; costruttori core attraverso `AbstractList`, `AbstractCollection`, `Object`; `EmptyArray.<clinit>` esegue `new-array`/`sput-object` e crea **un solo** array statico vuoto condiviso; `FolderInfo.unbind()` invoca `ItemInfo.unbind()` e, tramite `invoke-virtual`, il vero `ArrayList.clear()` | Il ramo vuoto di `clear` evita `Arrays.fill`; per una lista non vuota quella chiamata statica raggiunta fallisce chiusa, non viene imitata dall'host |
| `java.util.ArrayList` | Campi reali `size=0`, `modCount=0`, `array` con lunghezza DEX 0; metodi reali `size()I` e `isEmpty()Z` interpretati, inclusi branch e `goto` | Heap temporaneo, non Java Collections completo |
| `android.graphics.Point` (`framework.jar`) | `Point.<clinit>` istanzia `Point$1` dal DEX, esegue il suo costruttore e assegna `CREATOR` dopo controllo dell'interfaccia `Parcelable.Creator`; `Point(240,320)`, `offset(10,-20)` e `hashCode()I` eseguono il vero bytecode: valori attesi `x=250, y=300`, hash `8050` | Dati geometrici Java, **non** View, Canvas né UI AOSP |
| `android.view.View$MeasureSpec` (`framework.jar`) | `makeMeasureSpec/getMode/getSize` con bytecode aritmetico reale, provati sull'host | Nessuna misurazione o disegno di `View` |

I valori provengono dai veri `class_def`, `class_data`, `field_id`, `method_id`, proto e `code_item`, non da campi preimpostati nell'host. `symbian/runtime/aosp_object_vm.{h,c}` usa al massimo **32 handle** di oggetti/array vuoti, 64 campi per oggetto, 64 registri, 4.096 code unit e un budget globale di 4.096 passi. I target dei salti sono validati contro i confini delle istruzioni; opcode sconosciuti anche in codice morto sono respinti. Un'invocazione statica riconosciuta ma non implementata **non** viene simulata: se raggiunta, restituisce `UNSUPPORTED`. Chiamate di metodi esterni hanno rollback dei campi dell'intero heap, dei nuovi handle e dei riferimenti statici se falliscono. Non esiste ancora un GC o una VM Dalvik generale.

`E63UiStore::ConstructObjectGraphFields` e `E63BootStore::ProbeObject` autenticano di nuovo i byte originali di APK/JAR, indici e DEX mediante pin SHA-256, mantenendo aperti gli `RFile` di sola lettura durante il bytecode. La diagnostica Symbian sul **tasto 2** costruisce `FolderInfo`, chiama `unbind`, legge i due oggetti `ArrayList` e l'array di `EmptyArray`, ed esegue `size/isEmpty` dai DEX. Il **tasto 3** costruisce `Point(240,320)` dal vero `framework.jar`, esegue `offset(10,-20)` e `hashCode`, legge `x/y`, e verifica che `CREATOR` sia un vero handle di `Point$1` inizializzato dal DEX; **questa specifica sequenza è compilata GCCE ma non è stata provata sul Nokia**. I tasti **1, 6–9** esercitano gli altri modelli. Le frasi visualizzate sono dipinte dal **controllo diagnostico nativo**, non da una `android.view.View`. `StrictActivityEvent` resta intenzionalmente privo di executor Android.

## Prove, artefatti e riproducibilità

- `python3 -m unittest tests.test_aosp42_object_vm -v`: **14/14** test mirati sul PC. Le fixture sono DEX autentici compressi con SHA-256 in `tests/fixtures/aosp42_dex/`. Test di bytecode volutamente alterato, non ammissibile sul target dopo la verifica SHA, verificano esecuzione reale e rifiuto di branch invalidi, `<clinit>`/costruttori `Point$1` alterati, interfaccia `Creator` mancante, gerarchia ciclica e metodi non supportati. Il test host verifica anche `Point.set/offset/hashCode`.
- `python3 -m unittest discover -s tests -v`: **139 test, OK (1 saltato)**. Sono verifiche PC, non un test hardware.
- SDK Nokia ripristinato **solo localmente sotto `build/toolchains/`** dopo licenza già accettata; bootclasspath AOSP e quattro APK UI ricostruiti dagli esatti checkout autorizzati. Crossbuild **GCCE/UREL** nuovamente eseguito e SIS9 verificato: `build/aosp42-object-diagnostic/e63android-aosp42-object-diagnostic.sisx`, **55.367.904 byte**, SHA-256 **`7bb160c24e39cd764484f2feb1928888f6aa9cae0b1d492b97eabe5a419b7cc0`** (autofirma locale nuova; un'altra firma/build cambia l'hash). I **44 payload** sono confrontati byte per byte con gli input originali pin-nati e con l'EXE GCCE appena compilato; dipendenza S60 FP1 `0x102032BE`. **Nessuna installazione, esecuzione, prestazione o UI AOSP è stata verificata sul Nokia.** L'output grande, l'SDK sotto licenza locale e i checkout sono in `build/` esclusa dallo snapshot; script, pin, test e fixture restano persistenti.
- Il diagnostico condivide l'**UID `0xE0B63E04`** con il porting Java 0.2: se installato volontariamente, può aggiornare/sostituire quella app sul telefono. Non provarlo senza backup, spazio su C: e accettazione dei rischi; non viene chiesto qui un test anticipato.

Se la cartella non persistente `build/` è ancora presente, dalla root del progetto:

```bash
python3 -m unittest tests.test_aosp42_object_vm -v
python3 -m unittest discover -s tests -q
python3 tools/build_aosp42_object_diagnostic_sis.py
```

Il builder cerca la toolchain privata in `build/toolchains/`; `SYMBIAN_TOOLCHAINS=/altro/percorso` prevale. Se `build/` non sopravvive allo snapshot, ripetere **solo i checkout indispensabili autorizzati**, in ordine (mai un checkout totale AOSP):

```bash
python3 tools/bootstrap_framework42_only.py
python3 tools/bootstrap_android42_dependencies.py
python3 tools/bootstrap_aosp42_ui.py
python3 tools/bootstrap_aosp42_host_tools.py
python3 tools/build_aosp42_bootclasspath.py --stage
python3 tools/build_aosp42_ui_apks.py
# Solo dopo accettazione personale della EULA Nokia:
NOKIA_SDK_LICENSE_ACCEPTED=1 bash tools/bootstrap_symbian_fp1.sh
python3 tools/build_aosp42_object_diagnostic_sis.py
```

I piccoli archivi GnuPoc/GCCE in `~/toolchains/gnupoc-downloads/` vanno conservati; l'SDK e le chiavi private locali **non** vanno redistribuiti.

## Mancanze bloccanti verso l'obiettivo richiesto

`android.graphics.Rect` rimane correttamente rifiutato: il suo `<clinit>` vero chiama `Pattern.compile`, non disponibile. `PointF` resta fuori dal sottoinsieme dei campi float. Mancano class loading generalizzato attraverso tutti i boot JAR, inizializzazione Java generale, array non vuoti, stringhe complete, eccezioni, thread/monitor, GC, JNI/native libraries, Binder, `ActivityThread`/`ActivityManager`/`PackageManager`, inflazione di risorse AAPT, `View`/`Canvas`/Surface/input Android e servizi. **Launcher.onCreate non viene eseguito**, `SystemUIService` non parte, FileManager Android su file Nokia non funziona in questo ramo. Il `SystemUI.apk` simulato e la UI MIDP precedenti restano separati. Il crossbuild e i test PC non rendono il pacchetto un sistema Android 4.2 né provano l'E63.
