# Bilancio dimensioni E63: 0.6 completa vs core 0.7 modulare

Il vincolo scelto è **SISX base sotto 20.000.000 byte**, non l'obbligo che il contenuto estratto stia tutto sotto 20 MB. Gli asset/dati su C: devono comunque scendere. La v0.6 rimane intatta per riprodurre l'esperimento completo: 55.379.048 byte SISX, 90.266.381 byte estratti (44 payload). La variante core 0.7: **16.220.160 byte SISX** e **30.019.093 byte estratti** (24 payload), riduzione del **70,7%** nel download e **66,7%** sui file installati. Queste dimensioni non misurano overhead o spazio temporaneo dell'installer Nokia.

| Blocco della 0.6 | SISX payload compressi, circa | Decisione 0.7 |
|---|---:|---|
| EXE/risorse Symbian | 0,08 MB | Ricompilati per la variante core e conservati |
| Sei APK shim storici + immagini RGB565 | 6,82 MB | Fuori dalla base; originali intatti nelle release storiche |
| Dieci boot JAR AOSP + `framework-res.apk` | 18,79 MB | Dieci JAR autentici conservati; `framework-res.apk` rinviato |
| Dieci DEX cache + indice classi | 7,93 MB | Conservati: verificano lo stesso JAR autentico, caricamento a piccoli blocchi |
| Quattro APK UI AOSP + indici + AXML | 21,75 MB | Fuori dalla base, **nessun falso Launcher/SystemUI** |

**Perché il codice non pesa 52 MB:** il precedente EXE ARM occupava 0,08 MB *nel SISX*. I grandi contributi erano JPEG/wallpaper tablet del Launcher2 (14,7 MB compressi), risorse multilingua/densità dei quattro APK e `framework-res.apk` (10,6 MB compressi), APK del ramo precedente (6,8 MB) e cache DEX duplicate rispetto ai JAR (7,9 MB). La variante base ha tagliato il materiale non necessario a DEX/JNI/Binder senza cancellare sorgenti, ricompilare Java in shim o chiamarlo Android completo. Conserva ora tutte le **10** classi bootclasspath JAR (11.729 classi totali), il supporto DEX verificato, la JNI ristretta e il broker IPC Symbian. Non esegue SystemServer, Activity o View.

## Lavoro necessario per un *Android tailored for Symbian*, non una sola compressione

1. **Profilo risorse Nokia E63:** ricompilare AOSP `framework-res` e gli APK autentici dagli stessi sorgenti/tag con `aapt` configurato per 320×240/mdpi e per le lingue realmente usate, eliminando wallpaper di grandi tablet e resource qualifiers inadatti. Validare ogni `resources.arsc`, manifest, ID, riferimento e firma Android. Non rimuovere asset ZIP a caso: produrrebbe APK con riferimenti rotti e UI non autentica.
2. **Moduli UI installabili verificati:** reali Launcher2, Settings, PackageInstaller, SystemUI e risorse framework fuori dal SISX base, distribuiti con un meccanismo di provisioning sicuro con SHA-256, firma, confini d'accesso alla cartella privata su C: e installazione/rollback testati su Nokia. **Attualmente non esiste un add-on UI verificato:** il full preview 0.6 è un pacchetto separato, non un add-on né una prova d'integrazione.
3. **VM e servizi veri:** JNI per oggetti/GC/loader e Binder completo, `SystemServer` e servizi, risorse e lifecycle `Activity/View` Java autentici adattati a Symbian. L'host diagnostico non va rinominato Android. Fino ad allora l'errore per Activity assente deve restare visibile.
4. **Storage e firma:** `/system` guest persistente di sola lettura sulla C: privata, dati di app su C: con cache limitata; `/dev/binder` resta solo IPC virtuale senza mappature di partizione. Per moduli/upgrade bisogna definire una chiave di firma stabile sotto controllo del proprietario: le chiavi effimere dei test non vanno pubblicate nel repository e una chiave perduta può bloccare un aggiornamento sul telefono.

Sorgenti e script del porting MIDP, release 0.1/0.2, SISX integrale 0.6 e APK/JAR non vengono eliminati. La copia base 0.7 non dimostra un Android avviato né il funzionamento sull'E63; serve un test fisico dopo backup e con spazio sufficiente.
