@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

:menu
cls
echo ============================================
echo   Iraqi Legal Translation Agent
echo ============================================
echo.
echo   1. Doctor (check environment)
echo   2. Translate AR -^> EN
echo   3. Translate EN -^> AR
echo   4. Batch translate
echo   5. Ingest corpus
echo   6. Build TM
echo   7. Launch UI
echo   8. Exit
echo.
set /p choice="Select option (1-8): "

if "%choice%"=="1" goto doctor
if "%choice%"=="2" goto ar_en
if "%choice%"=="3" goto en_ar
if "%choice%"=="4" goto batch
if "%choice%"=="5" goto ingest
if "%choice%"=="6" goto tm_build
if "%choice%"=="7" goto ui
if "%choice%"=="8" exit /b 0
goto menu

:doctor
echo.
.\.venv310\Scripts\python.exe -m src.app doctor
echo.
pause
goto menu

:ar_en
echo.
set /p text="Enter Arabic text: "
echo.
.\.venv310\Scripts\python.exe -m src.app translate --input "%text%" --direction ar-en
echo.
pause
goto menu

:en_ar
echo.
set /p text="Enter English text: "
echo.
.\.venv310\Scripts\python.exe -m src.app translate --input "%text%" --direction en-ar
echo.
pause
goto menu

:batch
echo.
set /p input="Input JSONL path (default: data\batch.jsonl): "
if "%input%"=="" set input=data\batch.jsonl
set /p output="Output JSONL path (default: data\results.jsonl): "
if "%output%"=="" set output=data\results.jsonl
echo.
.\.venv310\Scripts\python.exe -m src.app batch --input "%input%" --output "%output%"
echo.
pause
goto menu

:ingest
echo.
.\.venv310\Scripts\python.exe -m src.app ingest
echo.
pause
goto menu

:tm_build
echo.
.\.venv310\Scripts\python.exe -m src.app tm-build
echo.
pause
goto menu

:ui
echo.
.\.venv310\Scripts\python.exe -m src.app ui
echo.
pause
goto menu
