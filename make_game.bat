@echo off
rem ------------------------------------------------------------------
rem  make_game.bat  -  double-click to turn a PGN into a web page + EPUB
rem  * Double-click it and pick a PGN from the games folder, or
rem  * drag a .pgn file onto this file.
rem ------------------------------------------------------------------
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title PGN to web page + EPUB

rem --- find Python ---
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python was not found. Install it from python.org, then try again.
    pause
    exit /b 1
)

rem --- install the two libraries the first time ---
%PY% -c "import chess, PIL" >nul 2>nul
if errorlevel 1 (
    echo Installing chess and pillow - only needed once...
    %PY% -m pip install chess pillow
)

rem --- which PGN? ---
set "PGN=%~1"
if defined PGN goto ask_stockfish

echo.
echo PGN files in the games folder:
echo.
set n=0
for %%F in ("games\*.pgn") do (
    set /a n+=1
    set "f!n!=%%~fF"
    echo    !n!. %%~nxF
)
if %n%==0 (
    echo    none yet.
    echo.
    echo Save your PGN in the games folder, then double-click this file again.
    pause
    exit /b 1
)
echo.
if %n%==1 (
    set "PGN=!f1!"
    echo Using the only one there.
    goto ask_stockfish
)
set "pick="
set /p "pick=Type the number of the PGN and press Enter: "
if not defined pick goto bad_pick
for /f "delims=0123456789" %%x in ("!pick!") do goto bad_pick
if !pick! LSS 1 goto bad_pick
if !pick! GTR %n% goto bad_pick
for %%i in (!pick!) do set "PGN=!f%%i!"
goto ask_stockfish

:bad_pick
echo That number isn't in the list.
pause
exit /b 1

:ask_stockfish
echo.
echo PGN: !PGN!
echo.
set "SF="
choice /c YN /n /m "Add Stockfish mistake diagrams? It takes a few minutes. [Y/N] "
if errorlevel 2 (set "SF=") else (set "SF=--stockfish")
echo.

%PY% make_game.py "!PGN!" !SF! --open
if errorlevel 1 (
    echo.
    echo Something went wrong - see the message above.
) else (
    echo.
    echo Done. The web page opens in your browser. Both files are in the out folder.
)
echo.
pause
