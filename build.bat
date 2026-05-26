@echo off
cd /d "%~dp0"
echo ========================================
echo  LLM File Translator - ビルド
echo ========================================
echo.

:: Pythonを確認
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Pythonが見つかりません。
    pause
    exit /b 1
)

:: PyInstallerを確認・インストール
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo PyInstallerをインストール中...
    pip install pyinstaller
)

:: 必要パッケージを確認・インストール
echo 依存パッケージを確認中...
pip install openai openpyxl python-docx rich json-repair --quiet

:: 旧ビルドを削除
if exist dist\LLM-Translator rmdir /s /q dist\LLM-Translator
if exist build rmdir /s /q build

:: ビルド実行
echo.
echo ビルド中...
pyinstaller app.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [ERROR] ビルドに失敗しました。
    pause
    exit /b 1
)

echo.
echo ========================================
echo  完了: dist\LLM-Translator\
echo  LLM-Translator.exe をダブルクリックして起動
echo ========================================
echo.
pause
