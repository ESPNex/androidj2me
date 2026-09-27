; Android J2ME Edition original project, 2024-06-04 snapshot.
; Single Windows executable including Java runtime. The source ZIP is left unchanged.
Unicode true
!include "x64.nsh"
Name "Android J2ME Edition"
OutFile "Android_J2ME_Edition_Originale.exe"
InstallDir "$LOCALAPPDATA\AndroidJ2MEEdition\originale-20240604-jre17-v1"
RequestExecutionLevel user
SilentInstall silent
AutoCloseWindow true
ShowInstDetails nevershow
SetCompressor /SOLID lzma
SetCompressorDictSize 16
Icon "build/windows/app.ico"

VIProductVersion "1.0.0.0"
VIAddVersionKey /LANG=1040 "ProductName" "Android J2ME Edition"
VIAddVersionKey /LANG=1040 "FileDescription" "Android J2ME Edition - progetto originale, Windows 64 bit"
VIAddVersionKey /LANG=1040 "FileVersion" "1.0.0.0"
VIAddVersionKey /LANG=1040 "OriginalFilename" "Android_J2ME_Edition_Originale.exe"
VIAddVersionKey /LANG=1040 "LegalCopyright" "Codice e componenti dei rispettivi autori."

Section "Avvia Android J2ME Edition"
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "Questo programma richiede Windows a 64 bit."
    Abort
  ${EndIf}

  ; A versioned private cache avoids collision with the old executable and avoids admin rights.
  IfFileExists "$INSTDIR\.ready" 0 extract
  IfFileExists "$INSTDIR\runtime\bin\javaw.exe" 0 extract
  IfFileExists "$INSTDIR\Android_J2ME_Edition_originale.jar" launch

extract:
  SetOutPath "$INSTDIR"
  File "build/windows/payload/Android_J2ME_Edition_originale.jar"
  SetOutPath "$INSTDIR\runtime"
  File /r "build/windows/payload/runtime/*"
  IfFileExists "$INSTDIR\runtime\bin\javaw.exe" 0 failure
  IfFileExists "$INSTDIR\Android_J2ME_Edition_originale.jar" 0 failure
  ClearErrors
  FileOpen $0 "$INSTDIR\.ready" w
  IfErrors failure
  FileWrite $0 "Android J2ME Edition originale 2024-06-04; Temurin 17.0.20.1+1"
  FileClose $0

launch:
  ClearErrors
  Exec '"$INSTDIR\runtime\bin\javaw.exe" -jar "$INSTDIR\Android_J2ME_Edition_originale.jar"'
  IfErrors failure
  Goto done

failure:
  MessageBox MB_OK|MB_ICONSTOP "Impossibile estrarre o avviare Android J2ME Edition. Controlla lo spazio disponibile e riprova."

done:
SectionEnd
