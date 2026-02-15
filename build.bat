@echo off
cd /d "%~dp0"
echo ============================================
echo   Building Whisper exe...
echo ============================================
echo.

pip install pyinstaller >nul 2>&1

pyinstaller --noconfirm --onedir --windowed ^
    --name "Whisper" ^
    --add-data "config.py;." ^
    --hidden-import "faster_whisper" ^
    --hidden-import "ctranslate2" ^
    --hidden-import "huggingface_hub" ^
    --hidden-import "tokenizers" ^
    --hidden-import "pystray" ^
    --hidden-import "PIL" ^
    --hidden-import "sounddevice" ^
    --hidden-import "keyboard" ^
    --hidden-import "_sounddevice_data" ^
    --hidden-import "webview" ^
    --hidden-import "clr" ^
    --hidden-import "clr_loader" ^
    --hidden-import "pythonnet" ^
    --hidden-import "bottle" ^
    --hidden-import "proxy_tools" ^
    voice_typer.py

if %errorlevel% neq 0 (
    echo.
    echo BUILD FAILED. Check errors above.
    pause
    exit /b 1
)

:: Copy config and icons next to exe so user can edit them
copy /y config.py dist\Whisper\ >nul 2>&1

echo.
echo ============================================
echo   Build complete!
echo   Output: dist\Whisper\Whisper.exe
echo ============================================
echo.
echo   To distribute: copy the entire dist\Whisper folder.
echo   config.py is included so users can edit settings.
echo.
pause
