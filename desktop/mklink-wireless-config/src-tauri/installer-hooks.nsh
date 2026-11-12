; A detached GUI can leave a flash job running in the independent backend.
!macro RemoteRequireStopped executable
  !insertmacro RestartManager_StartSession $R0
  ${If} $R0 == ""
    SetErrorLevel 2
    Abort "Cannot check running Mklink processes. Close Mklink and retry."
  ${EndIf}
  !insertmacro RestartManager_RegisterFile $R0 "${executable}"
  ${If} $0 = 0
    System::Call 'RSTRTMGR::RmGetList(i R0, *i .r1, *i .r2, p 0, *i .r3) i .r0'
  ${EndIf}
  StrCpy $R4 $0
  !insertmacro RestartManager_EndSession $R0
  ${If} $R4 != 0
    SetErrorLevel 2
    Abort "Mklink files are in use or could not be checked. Finish target jobs and close Mklink and its backend before retrying."
  ${EndIf}
!macroend

!macro RemoteRequireAllStopped
  !insertmacro RemoteRequireStopped "$INSTDIR\mklink-wireless-config.exe"
  !insertmacro RemoteRequireStopped "$INSTDIR\mklink-remote.exe"
  !insertmacro RemoteRequireStopped "$INSTDIR\resources\device-tool\remote-server\mklink-remote-server.exe"
!macroend

; Interactive upgrades can run the previous uninstaller before PREINSTALL.
!define MUI_CUSTOMFUNCTION_GUIINIT RemoteGuardBeforeReinstall
Function RemoteGuardBeforeReinstall
  !insertmacro RemoteRequireAllStopped
FunctionEnd

!macro NSIS_HOOK_PREINSTALL
  !insertmacro RemoteRequireAllStopped
  ; Frozen dependencies removed between releases must not survive an upgrade.
  IfFileExists "$INSTDIR\resources\device-tool\remote-server\*.*" 0 remote_cleanup_done
  IfFileExists "$INSTDIR\resources\device-tool\remote-server\mklink-remote-server.exe" remote_cleanup 0
    SetErrorLevel 2
    Abort "Unrecognized private backend directory; installation stopped without deleting it."
  remote_cleanup:
    ClearErrors
    RMDir /r "$INSTDIR\resources\device-tool\remote-server"
    ${If} ${Errors}
      SetErrorLevel 2
      Abort "Could not remove the old private backend. Close Mklink and retry installation."
    ${EndIf}
  remote_cleanup_done:
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro RemoteRequireAllStopped
!macroend

; The help guide and maintenance workflow should be discoverable after install
; and update. Keep NSIS's explicit /NS no-shortcut option respected.
!macro NSIS_HOOK_POSTINSTALL
  ${If} $NoShortcutMode != 1
    SetOutPath "$INSTDIR"
    CreateShortcut "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe" "" "$INSTDIR\resources\branding\MklinkRemote.ico" 0
    !insertmacro SetLnkAppUserModelId "$DESKTOP\${PRODUCTNAME}.lnk"
  ${EndIf}
!macroend
