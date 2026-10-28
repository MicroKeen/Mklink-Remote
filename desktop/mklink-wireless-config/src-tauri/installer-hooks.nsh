; The help guide and maintenance workflow should be discoverable after install
; and update. Keep NSIS's explicit /NS no-shortcut option respected.
!macro NSIS_HOOK_POSTINSTALL
  ${If} $NoShortcutMode != 1
    SetOutPath "$INSTDIR"
    CreateShortcut "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe" "" "$INSTDIR\resources\branding\MklinkRemote.ico" 0
    !insertmacro SetLnkAppUserModelId "$DESKTOP\${PRODUCTNAME}.lnk"
  ${EndIf}
!macroend
