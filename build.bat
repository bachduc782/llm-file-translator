@echo off
cd /d "%~dp0"
echo ========================================
echo  LLM File Translator - ビルド
echo ========================================
echo.

set DIST=dist\LLM-Translator

:: Pythonを確認
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Pythonが見つかりません。Pythonをインストールしてください。
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python -c "import sys; print(sys.executable)"') do set PYTHON_EXE=%%i
echo Python: %PYTHON_EXE%
echo.

:: 旧ビルドを削除
if exist %DIST% rmdir /s /q %DIST%
mkdir %DIST%\packages

:: 依存パッケージをローカルフォルダへインストール
echo [1/3] パッケージをインストール中...
"%PYTHON_EXE%" -m pip install ^
  openai openpyxl python-docx rich json-repair ^
  --target %DIST%\packages ^
  --no-warn-script-location -q

if errorlevel 1 (
    echo [ERROR] パッケージのインストールに失敗しました。
    pause
    exit /b 1
)

:: アプリファイルをコピー
echo [2/3] アプリファイルをコピー中...
copy /y app.py        %DIST%\
copy /y engine.py     %DIST%\
copy /y app_config.py %DIST%\

:: ランチャーを作成
echo [3/3] ランチャーを作成中...
(
  echo @echo off
  echo cd /d "%%~dp0"
  echo set PYTHONPATH=%%~dp0packages
  echo python app.py %%*
  echo if errorlevel 1 pause
) > %DIST%\run.bat

echo.
echo ========================================
echo  完了: %DIST%\
echo  run.bat をダブルクリックして起動
echo  ※ 実行先にもPythonのインストールが必要です
echo ========================================
echo.
pause
