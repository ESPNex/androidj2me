# Android J2ME / Nokia E63 — sorgenti e release storiche

**Stato reale:** il porting MIDP e le precedenti release 0.2 rimangono separati. Il nuovo eseguibile S60 è un *preview sperimentale* con un sottoinsieme di DEX, JNI e IPC Binder; **non avvia Android 4.2, SystemServer, Activity o View sul Nokia**. Nessuna prova hardware è stata eseguita.

- `DalvikE63/`: sorgenti Symbian/C99, build riproducibili, APK e JAR precedenti, test e note architetturali. Leggere `DalvikE63/docs/aosp42_vm_jni_binder_status.md`.
- `NokiaE63_MIDP/`: porting precedente e asset, preservati; i tool JAR di terze parti non sono caricati.
- `progetto_originale/`: sorgenti Java ME originali e relative risorse.
- `Android_J2ME_E63.jad` e `Android_J2ME_E63.jar`: distribuzione J2ME originale abbinata (JAD 3.461.012 byte), conservata senza modifiche.
- `DalvikE63/release/`: precedenti SISX/JAR 0.2 e altri file storici, non sovrascritti.
- [Base E63 modulare v0.7-core-preview](https://github.com/ESPNex/androidj2me/releases/tag/v0.7-core-preview): SISX **16.220.160 byte** (<20 MB), SHA-256 `2207f1cd2d1678d2047cae8a51b66f48342e856d703490768f81ae99caf31706`, 24 payload e circa 30 MB installati. Solo codice DEX AOSP autentico/diagnostica JNI-Binder; **non ha ancora APK UI o un Android avviabile**. Leggere [avvertenze, limiti e backup](DalvikE63/release/experiments/LEGGIMI-E63-CORE-SOTTO20MB.md).
- [Release sperimentale v0.6-preview](https://github.com/ESPNex/androidj2me/releases/tag/v0.6-preview): SISX rigenerato e firmato con certificato locale **come asset separato**, troppo grande per lo snapshot workspace. Leggere `DalvikE63/release/experiments/LEGGIMI-JNI-BINDER-PREVIEW.md` prima di usare il file.

I sorgenti AOSP autorizzati sono acquisiti tramite gli script con tag/commit fissati sotto `DalvikE63/build/` escluso; non è un checkout AOSP completo. Anche lo SDK Nokia FP1 richiede licenza e installazione locale; **non viene redistribuito**. Il vecchio installer Windows originale rimane nel workspace dell'autore e non è caricato su questo repository pubblico.

Verifica di sviluppo: `python3 -m unittest discover -s tests -p 'test_*.py' -q` nella cartella `DalvikE63/`: 147 test, 3 saltati nel clone pulito (151 test, 2 saltati con bootclasspath AOSP ristaged localmente). La compilazione GCCE e la verifica strutturale del SISX non sostituiscono un test sul telefono fisico.
