@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "VER=1.0"
set "PATCHOLLY_NOBANNER=1"
set "EXENAME=CCleaner.exe"
title Patcholly CCleaner Classic Patcher v%VER%

rem ---- are we running as administrator? ----
set "ISADMIN="
fltmc >nul 2>&1 && set "ISADMIN=1"

rem ---- find Python (bundled embeddable first, then system) ----
set "PY="
if exist "%~dp0Python\python.exe" set PY="%~dp0Python\python.exe"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    echo Python not found.
    echo Extract python-3.14.10-embed-amd64.zip into the "Python"
echo folder ^(see Python\PUT_PYTHON_HERE.txt^).
    pause
    exit /b 1
)
color 0A

rem ---- elevated helper: an action handed over by the normal (non-admin) window ----
set "PENDING="
set "PTARGET="
set "ACTION="
set /a RLN=0
set /a FCOUNT=0
if exist "%~dp0_pending.txt" (
    for /f "usebackq delims=" %%L in ("%~dp0_pending.txt") do call :pline "%%L"
    del "%~dp0_pending.txt" >nul 2>&1
)
if defined PENDING goto resume

call :banner

rem ---- a file dragged ONTO Patch_CCleaner.cmd (passed as a parameter) ----
if not "%~1"=="" (
    set "EXE=%~1"
    set "FROMICON=1"
    goto dropped
)

:menu
echo.
echo  ================================================================
echo   Patcholly Classic Patcher v%VER%
echo  ================================================================
echo   01  Patch CCleaner.exe        (X = exit, - = tray)
echo   02  Dry run                   (show what would change)
echo   03  Restore original CCleaner.exe
echo   04  Apply grey theme
echo   05  Undo grey theme
echo   06  Patch a CCleaner.exe you pick
echo   07  Grey theme on a CCleaner.exe you pick
echo   00  Quit
echo.
echo   01-05 auto-find CCleaner in Program Files and on the Desktop.
echo   Tip: drag CCleaner.exe into this window, then press Enter.
echo.
set "CHOICE="
set /p "CHOICE=Choose a number (or drag CCleaner.exe here): "
rem a file dragged into this window is pasted here as text: drop the quotes and trailing spaces
set "CHOICE=%CHOICE:"=%"
:trimchoice
if not defined CHOICE goto choicetrimmed
if not "%CHOICE:~-1%"==" " goto choicetrimmed
set "CHOICE=%CHOICE:~0,-1%"
goto trimchoice
:choicetrimmed
if "%CHOICE%"=="1"  goto patch
if "%CHOICE%"=="01" goto patch
if "%CHOICE%"=="2"  goto dry
if "%CHOICE%"=="02" goto dry
if "%CHOICE%"=="3"  goto restore
if "%CHOICE%"=="03" goto restore
if "%CHOICE%"=="4"  goto grey
if "%CHOICE%"=="04" goto grey
if "%CHOICE%"=="5"  goto greyundo
if "%CHOICE%"=="05" goto greyundo
if "%CHOICE%"=="6"  goto browse
if "%CHOICE%"=="06" goto browse
if "%CHOICE%"=="7"  goto browsegrey
if "%CHOICE%"=="07" goto browsegrey
if "%CHOICE%"=="0"  goto quit
if "%CHOICE%"=="00" goto quit
rem a CCleaner.exe path dragged into the window -> patch it
if /I "%CHOICE:~-12%"=="CCleaner.exe" (
    set "DROPPED=%CHOICE%"
    goto windrop
)
if defined CHOICE if exist "%CHOICE%" (
    call :red "That is not CCleaner.exe - drag CCleaner.exe itself."
    goto menu
)
call :red "Invalid choice - type a menu number, or drag CCleaner.exe into this window."
goto menu

:windrop
rem %DROPPED% is a path captured at the menu (may contain spaces); hand it to :dropped
set "EXE=%DROPPED%"
set "DROPPED="
goto dropped

:quit
color 07
exit /b 0

rem ================= elevation hand-off =================
rem Runs an action as administrator in a separate window, leaving THIS window
rem non-elevated so files can still be dragged into it.
rem  %1 = action keyword   %2 = optional target file (quoted)
:runadmin
>"%~dp0_pending.txt" echo(%~1
if not "%~2"=="" >>"%~dp0_pending.txt" echo(%~2
set "CCP_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath $env:CCP_SELF -Verb RunAs -ErrorAction Stop } catch { exit 1 }"
if errorlevel 1 (
    del "%~dp0_pending.txt" >nul 2>&1
    call :red "Elevation was cancelled - nothing was changed."
)
exit /b 0

rem ---- read one line of _pending.txt (keyword, then either a target or a RUNLIST) ----
:pline
set /a RLN+=1
if %RLN%==1 ( set "PENDING=%~1" & exit /b 0 )
if /I "%PENDING%"=="RUNLIST" goto plinelist
if %RLN%==2 set "PTARGET=%~1"
exit /b 0
:plinelist
if %RLN%==2 ( set "ACTION=%~1" & exit /b 0 )
set /a FCOUNT+=1
set "FND_%FCOUNT%=%~1"
exit /b 0

rem ================= elevated helper resumes here =================
:resume
call :banner
if /I "%PENDING%"=="RUNLIST" goto runlist
if "%PENDING%"=="DROPPATCH" goto resumedrop
if "%PENDING%"=="GREYONE"   goto resumegrey
goto workerdone

:runlist
rem ACTION and FND_1..FCOUNT were found in the NON-admin window (your real Desktop)
if %FCOUNT%==0 goto workerdone
set /a I=0
:runlistloop
set /a I+=1
if %I% GTR %FCOUNT% goto workerdone
call set "EXE=%%FND_%I%%%"
for %%D in ("%EXE%") do (
    set "EXEDIR=%%~dpD"
    set "EXENAME=%%~nxD"
)
call :savelast
echo.
echo ---- %I% of %FCOUNT% : "%EXE%"
call :%ACTION%
goto runlistloop

:resumedrop
set "EXE=%PTARGET%"
for %%D in ("%EXE%") do (
    set "EXEDIR=%%~dpD"
    set "EXENAME=%%~nxD"
)
if not exist "%EXE%" ( call :red "File not found." & goto workerdone )
call :savelast
echo.
echo Dropped: "%EXE%"
call :patchone
goto workerdone

:resumegrey
set "EXE=%PTARGET%"
for %%D in ("%EXE%") do (
    set "EXEDIR=%%~dpD"
    set "EXENAME=%%~nxD"
)
call :savelast
call :greyone
goto workerdone

:runallw
call :getfiles || goto workerdone
set /a I=0
:runloopw
set /a I+=1
if %I% GTR %FCOUNT% goto workerdone
call set "EXE=%%FND_%I%%%"
for %%D in ("%EXE%") do (
    set "EXEDIR=%%~dpD"
    set "EXENAME=%%~nxD"
)
call :savelast
echo.
echo ---- %I% of %FCOUNT% : "%EXE%"
call :%ACTION%
goto runloopw

:workerdone
echo.
echo Done - this window will close.
pause >nul
exit

rem ================= file pickers =================
:pick
set "EXE="
call :loadlast
for /f "usebackq delims=" %%F in (`powershell -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0pick_ccleaner_files.ps1" %IDIR%`) do set "EXE=%%F"
goto pickdone

:pickgrey
set "EXE="
call :loadlast
for /f "usebackq delims=" %%F in (`powershell -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0pick_ccleaner_files.ps1" -Grey %IDIR%`) do set "EXE=%%F"
goto pickdone

:pickany
set "EXE="
call :loadlast
for /f "usebackq delims=" %%F in (`powershell -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0pick_ccleaner_files.ps1" -Any %IDIR%`) do set "EXE=%%F"
goto pickdone

:pickdone
if not defined EXE (
    echo No file selected.
    exit /b 1
)
for %%D in ("%EXE%") do (
    set "EXEDIR=%%~dpD"
    set "EXENAME=%%~nxD"
)
call :savelast
exit /b 0

:savelast
rem remember where the file was, so the pickers open there next time
set "SAVEDIR=%EXEDIR%"
rem if a theme .css (gui\assets) was picked, remember the CCleaner folder two levels up instead
if /I "%EXENAME:~-4%"==".css" for %%A in ("%EXEDIR%..\..") do set "SAVEDIR=%%~fA\"
>"%~dp0last_folder.txt" echo(%SAVEDIR%
exit /b 0

:loadlast
set "LASTDIR="
if exist "%~dp0last_folder.txt" set /p LASTDIR=<"%~dp0last_folder.txt"
set "IDIR="
if defined LASTDIR if exist "%LASTDIR%" set "IDIR=-InitialDir "%LASTDIR:~0,-1%""
exit /b 0

:findall
rem finds EVERY CCleaner.exe in Program Files, on the Desktop and inside the patcher folder
set /a FCOUNT=0
echo Searching for CCleaner.exe in Program Files, on the Desktop and in the patcher folder ...
for /f "usebackq delims=" %%F in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_ccleaner.ps1" -ScriptDir "%~dp0."`) do call :addfound "%%F"
exit /b 0

:addfound
set /a FCOUNT+=1
call set "FND_%FCOUNT%=%~1"
echo   Found: "%~1"
exit /b 0

:getfiles
call :findall
if %FCOUNT% GTR 0 exit /b 0
echo.
echo CCleaner was not found automatically - please select it.
call :%PICKER% || exit /b 1
set "FND_1=%EXE%"
set /a FCOUNT=1
exit /b 0

rem ================= running-detector =================
:isrunning
set "RUNNING="
for %%N in (CCleaner64.exe CCleaner.exe CCleanerBrowser.exe CCleanerDU.exe "%EXENAME%") do (
    tasklist /FI "IMAGENAME eq %%~N" 2>nul | find /I "%%~N" >nul && set "RUNNING=1"
)
exit /b 0

:closecc
call :isrunning
if not defined RUNNING exit /b 0
echo.
echo CCleaner (or its error window) is open - closing it ...
rem force-close at once: a modal "cannot start / WebView2" dialog ignores a gentle close
for %%N in (CCleaner64.exe CCleaner.exe CCleanerBrowser.exe CCleanerDU.exe "%EXENAME%") do taskkill /F /T /IM "%%~N" >nul 2>&1
set /a TRIES=0
:waitloop
timeout /t 1 /nobreak >nul
call :isrunning
if not defined RUNNING goto closed
set /a TRIES+=1
for %%N in (CCleaner64.exe CCleaner.exe CCleanerBrowser.exe CCleanerDU.exe "%EXENAME%") do taskkill /F /T /IM "%%~N" >nul 2>&1
if %TRIES% GEQ 10 goto closefail
goto waitloop
:closed
echo Closed - continuing ...
exit /b 0
:closefail
call :red "Could not close CCleaner. Close it manually or run this script as administrator."
exit /b 1

rem ================= coloured messages (yellow = success, red = problem) =================
:yellow
powershell -NoProfile -Command "Write-Host '%~1' -ForegroundColor Yellow"
exit /b 0
:darkred
powershell -NoProfile -Command "Write-Host '%~1' -ForegroundColor DarkRed"
exit /b 0
:red
powershell -NoProfile -Command "Write-Host '%~1' -ForegroundColor Red"
exit /b 0

rem ================= actions (menu) =================
rem Each action needs admin. If this window is not elevated, hand the job to an
rem elevated helper window and keep this one for more drag-and-drop.
:patch
set "PICKER=pick"
set "ACTION=patchone"
goto prep

:dry
set "PICKER=pick"
set "ACTION=dryone"
goto prep

:restore
set "PICKER=pick"
set "ACTION=restoreone"
goto prep

:grey
set "PICKER=pickgrey"
set "ACTION=greyone"
goto prep

:greyundo
set "PICKER=pickgrey"
set "ACTION=greyundoone"
goto prep

:prep
rem search in THIS window so YOUR Desktop/profile is used, then patch (elevating if needed)
call :getfiles || goto menu
if defined ISADMIN goto runall
call :runadminlist
goto menu

:runadminlist
rem hand the found list + action to an elevated helper (search already done as you)
>"%~dp0_pending.txt" echo(RUNLIST
>>"%~dp0_pending.txt" echo(%ACTION%
set /a J=0
:rlwrite
set /a J+=1
if %J% GTR %FCOUNT% goto rlgo
call set "F=%%FND_%J%%%"
>>"%~dp0_pending.txt" echo(%F%
goto rlwrite
:rlgo
set "CCP_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath $env:CCP_SELF -Verb RunAs -ErrorAction Stop } catch { exit 1 }"
if errorlevel 1 (
    del "%~dp0_pending.txt" >nul 2>&1
    call :red "Elevation was cancelled - nothing was changed."
)
exit /b 0

:runall
set /a I=0
:runloop
set /a I+=1
if %I% GTR %FCOUNT% goto menu
call set "EXE=%%FND_%I%%%"
for %%D in ("%EXE%") do (
    set "EXEDIR=%%~dpD"
    set "EXENAME=%%~nxD"
)
call :savelast
echo.
echo ---- %I% of %FCOUNT% : "%EXE%"
call :%ACTION%
goto runloop

:browse
call :pickany || goto menu
echo Selected: "%EXE%"
set "OK="
set /p "OK=Patch this file? (Y/N): "
if /I not "%OK%"=="Y" goto menu
if not defined ISADMIN ( call :runadmin DROPPATCH "%EXE%" & goto menu )
call :patchone
goto menu

:browsegrey
call :pickgrey || goto menu
echo Selected: "%EXE%"
set "OK="
set /p "OK=Apply the grey theme to this CCleaner? (Y/N): "
if /I not "%OK%"=="Y" goto menu
if not defined ISADMIN ( call :runadmin GREYONE "%EXE%" & goto menu )
call :greyone
goto menu

rem ================= drag and drop: CCleaner.exe dragged in / dropped on =================
:dropped
for %%D in ("%EXE%") do (
    set "EXEDIR=%%~dpD"
    set "EXENAME=%%~nxD"
)
if not exist "%EXE%" ( call :red "File not found." & goto dropend )
if /I not "%EXENAME%"=="CCleaner.exe" ( call :red "Only CCleaner.exe can be dragged onto the patcher." & goto dropend )
call :savelast
rem dragging the .exe can make Windows launch CCleaner - close it now, then patch
call :closecc
if defined ISADMIN (
    echo.
    echo Dropped: "%EXE%"
    call :patchone
    goto dropend
)
call :runadmin DROPPATCH "%EXE%"
:dropend
if defined FROMICON exit /b 0
goto menu

:patchone
call :closecc || exit /b 1
echo Patching "%EXE%" ...
echo.
%PY% "%~dp0ccleaner7_tray_patch.py" "%EXE%"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    call :darkred "Successfully patched: %EXE%"
    exit /b 0
)
if "%RC%"=="3" (
    call :red "This file is already patched (no changes needed): %EXE%"
    echo Use menu 03 to restore the original first if you want to patch it again.
    exit /b 0
)
if "%RC%"=="2" (
    call :red "CCleaner only partly patched - see the messages above."
) else (
    call :red "Patching failed - see the messages above."
)
call :hint
exit /b 1

:dryone
%PY% "%~dp0ccleaner7_tray_patch.py" "%EXE%" --dry-run
exit /b 0

:restoreone
if not exist "%EXE%.bak" (
    echo No backup found next to the file: "%EXE%.bak"
    exit /b 1
)
call :closecc || exit /b 1
copy /Y "%EXE%.bak" "%EXE%" >nul
if errorlevel 1 (
    call :red "Restore failed."
    call :hint
    exit /b 1
)
call :darkred "Original CCleaner restored successfully"
exit /b 0

rem ================= grey theme =================
:greyone
call :closecc
echo Applying grey theme in "%EXEDIR:~0,-1%" ...
%PY% "%~dp0grey_theme_patch.py" "%EXEDIR:~0,-1%"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    call :darkred "Grey theme successfully applied: %EXE%"
    exit /b 0
)
if "%RC%"=="4" (
    call :darkred "The grey theme is already applied here: %EXE%"
    echo Use menu 05 to undo it first if you want to apply it again.
    exit /b 0
)
if "%RC%"=="3" (
    call :red "CCleaner gui\assets folder not found here: %EXE%"
) else (
    call :red "Grey theme failed - see the messages above."
)
call :hint
exit /b 1

:greyundoone
call :closecc
%PY% "%~dp0grey_theme_patch.py" --undo "%EXEDIR:~0,-1%"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    call :darkred "Grey theme successfully removed: %EXE%"
    exit /b 0
)
if "%RC%"=="1" (
    call :darkred "No grey theme backup found here - nothing to undo: %EXE%"
    exit /b 0
)
call :red "Undo failed - see the messages above."
call :hint
exit /b 1

rem ================= helpers =================
:hint
echo.
echo If the message says "Permission denied", right-click Patch_CCleaner.cmd
echo and choose "Run as administrator" (CCleaner lives in Program Files).
exit /b 0

:banner
echo(===================================================================
echo.
echo(  ####    ###   #####   ####  #   #   ###   #      #      #   #
echo(  #   #  #   #    #    #      #   #  #   #  #      #       # #
echo(  ####   #####    #    #      #####  #   #  #      #        #
echo(  #      #   #    #    #      #   #  #   #  #      #        #
echo(  #      #   #    #     ####  #   #   ###   #####  #####    #
echo.
echo(             CCLEANER CLASSIC PATCHER  //  v%VER%
echo(===================================================================
exit /b 0
