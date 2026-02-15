@echo off
cd /d "%~dp0"
echo ============================================
echo   Building Whisper exe...
echo ============================================
echo.

pip install pyinstaller >nul 2>&1

pyinstaller --noconfirm --onedir --windowed ^
    --name "Whisper" ^
    --icon "icon.ico" ^
    --add-data "config.py;." ^
    --add-data "icon.ico;." ^
    --add-data "icon.png;." ^
    --add-data "mic_on.wav;." ^
    --add-data "mic_off.wav;." ^
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

echo.
echo ============================================
echo   Build complete!
echo   Output: dist\Whisper\Whisper.exe
echo ============================================
echo.
echo   Zip the dist\Whisper folder to distribute.
echo.
pause
