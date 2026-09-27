# Android J2ME Edition — Nokia E63

Porting **Java ME reale** del progetto originale: **MIDP 2.0 / CLDC 1.1**, Canvas/LCDUI, navigazione con D-pad e risorse grafiche/sonore adattate dall'archivio di partenza. Non è un JAR desktop rinominato e non richiede Swing o touchscreen. Le schermate riprendono diciture, colori, immagini e gerarchia originali; dimensioni, a capo, scrolling e indicatori di selezione sono adattati al display orizzontale **320 × 240** dell'E63. Le etichette aggiunte per la modalità offline sono state rimosse dall'interfaccia.

## Installazione

1. Copia `Android_J2ME_E63.jar` e `Android_J2ME_E63.jad` **nella stessa cartella** del Nokia E63; il JAD punta al nome relativo del JAR.
2. Dal gestore file apri il JAD e conferma l'installazione. Se il telefono non apre JAD locali, prova il JAR direttamente.
3. Avvia **Android J2ME Edition** dal menu delle applicazioni Java.

La versione corretta è **1.0.3**. Se hai già installato la 1.0.0, la 1.0.1 o la 1.0.2, copia **sia il nuovo JAR sia il nuovo JAD** e conferma l'aggiornamento aprendo il JAD: non usare un vecchio JAR rimasto sul telefono. Evita di disinstallare prima se vuoi provare a mantenere lo stato RMS (il comportamento dell'aggiornamento su E63 fisico non è stato verificato).

L'installazione, i softkey e il tasto Home su un Nokia E63 fisico **non sono stati verificati**. Sono stati provati i viewport **320 × 240** e **320 × 200** in MicroEmulator. A 320 × 200 i comandi dell'editor nativo possono non apparire sul bordo inferiore nell'emulatore, ma restano azionabili da tastiera (**F1 per annullare, F2 per confermare** nella configurazione usata per i test).

## Comandi

- **D-pad**: sposta la selezione; la freccia sinistra non equivale a Indietro. Le liste più lunghe scorrono mantenendo visibile la riga attiva.
- **Softkey fisico sinistro dell'E63**: Indietro (su Canvas Nokia: `-6`). **Softkey destro** e **tasto centrale Navi/OK**: conferma, apre un campo da modificare o aziona un pulsante. I comandi Canvas non intercettano i softkey.
- **Tasto Home fisico dell'E63**: il programma tenta di riconoscerlo quando la pressione è consegnata al MIDlet. Se Symbian lo gestisce per aprire la Home **del telefono**, il programma non può impedirlo: al ritorno nell'app mostra la Home interna quando riceve la notifica di sospensione/nascondimento. Il tasto **`#` fuori dai campi** è una scorciatoia affidabile per la Home interna.
- Seleziona **Email**, **Password** o **Search** e premi Navi/OK: si apre un **campo di testo MIDP nativo**, modificabile con la tastiera QWERTY e il metodo d'immissione del telefono. Nell'editor **`..`/Indietro è sul softkey sinistro** e **OK su quello destro**; Backspace cancella i caratteri.
- In alternativa, se il dispositivo invia i codici MIDP corrispondenti: **2/4** su/sinistra, **8/6** giù/destra, **5** conferma, **0 o `*`** torna indietro (fuori dai campi).

I tre campi rimangono visibili sulle schermate originali; **la modifica avviene nell'editor MIDP nativo** perché la digitazione direttamente su Canvas non era affidabile con la tastiera E63. La Password è mascherata: durante l'immissione il componente nativo conserva temporaneamente i caratteri, ma il MIDlet non li legge come testo, svuota il campo quando lo si chiude e conserva solo il conteggio per la maschera. Email e Password non sono inviati né salvati in RMS; Email è rimossa quando si lascia la schermata. Si può premere la freccia **Next** anche lasciando i campi vuoti. La percentuale della batteria usa cifre ingrandite (6 × 10 pixel) che restano all'interno della barra.

## Funzioni della demo

Lo Store e l'account sono una **simulazione offline**: non accedono a Google Play. Il Wi-Fi mostrato nell'app resta simulato; File Manager mostra contenuti del progetto, non esplora i file privati del Nokia.

La batteria **non è più simulata**: il MIDlet interroga periodicamente la proprietà Nokia `com.nokia.mid.batterylevel`. Se il firmware restituisce un valore valido da 0 a 100, la barra e le cifre indicano quella lettura; a carica bassa l'avviso usa la stessa lettura. Se la proprietà manca, è negata o non è interpretabile, compare **`?` in una barra grigia**: nessuna percentuale inventata e nessuno spegnimento automatico. Questa proprietà non è standard MIDP ed è ancora da verificare **sull'E63 fisico**; MicroEmulator non fornisce la batteria reale del PC.

La dicitura del pulsante è **INSTALL** prima e **OPEN** dopo l'installazione simulata. **OPEN apre File Manager senza reinstallare**. L'installazione, la scelta Wi-Fi e le impostazioni dell'app vengono conservate in RMS anche dopo il riavvio; **Email e Password no**. La ricerca permette di trovare File Manager oppure visualizza la schermata originale senza risultati.

I WAV inclusi sono riprodotti tramite MMAPI/JSR-135 se supportato dal telefono. L'audio non è stato verificato sull'E63; l'emulatore usato per i test non ha fornito una riproduzione audio affidabile.

## Sorgenti e ricompilazione

- Java ME: `src/android/j2me/edition/`
- Risorse derivate dall'originale: `res/` (rigenerabili con `python3 tools/prepare_assets.py`)
- Toolchain locale: `toolchain/`
- Dalla cartella `NokiaE63_MIDP/`, esegui **`bash build.sh`**. I file risultanti sono `../Android_J2ME_E63.jar` e `../Android_J2ME_E63.jad`.

La compilazione produce classi **45.3 preverificate (StackMap CLDC)**, manifest MIDP 2.0/CLDC 1.1 e un JAD con `MIDlet-Jar-Size` aggiornato. I test su MicroEmulator coprono il softkey sinistro simulato (F1), il destro (F2), D-pad distinto dai softkey, i tre campi editabili, la barra con livello sconosciuto e con un valore iniettato (73%), INSTALL → OPEN e i layout 320 × 240 / 320 × 200. L'emulatore **non verifica il tasto Home fisico, la batteria o la tastiera di un E63 reale**.
