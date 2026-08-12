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
echo   1.  Doctor (check environment)
echo   2.  Translate AR -^> EN
echo   3.  Translate EN -^> AR
echo   4.  Translate (auto-detect direction)
echo   5.  Batch translate (JSONL)
echo   6.  Translate Excel (.xlsx)
echo   7.  Translate Word (.docx)
echo   8.  Translate PDF (.pdf)
echo   9.  Ingest corpus
echo   10. Build TM (from corpus)
echo   11. Build TM (from parallel JSONL)
echo   12. Add parallel pairs to TM
echo   13. Launch UI
echo   14. Exit
echo.
set /p choice="Select option (1-14): "

if "%choice%"=="1" goto doctor
if "%choice%"=="2" goto ar_en
if "%choice%"=="3" goto en_ar
if "%choice%"=="4" goto auto
if "%choice%"=="5" goto batch
if "%choice%"=="6" goto excel
if "%choice%"=="7" goto word
if "%choice%"=="8" goto pdf
if "%choice%"=="9" goto ingest
if "%choice%"=="10" goto tm_build
if "%choice%"=="11" goto tm_build_parallel
if "%choice%"=="12" goto tm_add_parallel
if "%choice%"=="13" goto ui
if "%choice%"=="14" exit /b 0
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

:auto
echo.
set /p text="Enter text (direction auto-detected by script): "
echo.
.\.venv310\Scripts\python.exe -m src.app translate --input "%text%" --direction auto
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
.\.venv310\Scripts\python.exe -m src.app batch --input "%input%" --out "%output%"
echo.
pause
goto menu

:excel
echo.
set /p input="Input .xlsx path: "
set /p output="Output .xlsx path: "
set /p direction="Direction (ar-en / en-ar / auto, default: auto): "
if "%direction%"=="" set direction=auto
echo.
.\.venv310\Scripts\python.exe -m src.app excel --input "%input%" --out "%output%" --direction %direction%
echo.
pause
goto menu

:word
echo.
set /p input="Input .docx path: "
set /p output="Output .docx path: "
set /p direction="Direction (ar-en / en-ar / auto, default: auto): "
if "%direction%"=="" set direction=auto
echo.
.\.venv310\Scripts\python.exe -m src.app word --input "%input%" --out "%output%" --direction %direction%
echo.
pause
goto menu

:pdf
echo.
set /p input="Input .pdf path: "
set /p output="Output sidecar path (.docx or .txt): "
set /p direction="Direction (ar-en / en-ar / auto, default: auto): "
if "%direction%"=="" set direction=auto
echo.
.\.venv310\Scripts\python.exe -m src.app pdf --input "%input%" --out "%output%" --direction %direction%
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

:tm_build_parallel
echo.
set /p jsonl="Path to parallel JSONL file: "
set /p maxpairs="Max pairs (default 10000): "
if "%maxpairs%"=="" set maxpairs=10000
echo.
.\.venv310\Scripts\python.exe -m src.app tm-build-parallel "%jsonl%" --max-pairs %maxpairs%
echo.
pause
goto menu

:tm_add_parallel
echo.
set /p jsonl="Path to parallel JSONL file: "
set /p maxpairs="Max pairs (default 10000): "
if "%maxpairs%"=="" set maxpairs=10000
echo.
.\.venv310\Scripts\python.exe -m src.app tm-add-parallel "%jsonl%" --max-pairs %maxpairs%
echo.
pause
goto menu

:ui
echo.
.\.venv310\Scripts\python.exe -m src.app ui
echo.
pause
goto menu
