@echo off
cd /d "%~dp0"
echo ========================================
echo  LLM File Translator - ビルド (埋め込みPython版)
echo ========================================
echo.

set DIST=dist\LLM-Translator
set PY_VER=3.11.9
set PY_ZIP=python-%PY_VER%-embed-amd64.zip
set PY_URL=https://www.python.org/ftp/python/%PY_VER%/%PY_ZIP%

:: 旧ビルドを削除
if exist %DIST% rmdir /s /q %DIST%
mkdir %DIST%\python

:: Python embeddableをダウンロード
echo [1/5] Python %PY_VER% をダウンロード中...
powershell -Command "Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_ZIP%' -UseBasicParsing"
if errorlevel 1 ( echo [ERROR] ダウンロード失敗 & pause & exit /b 1 )

:: 展開
echo [2/5] 展開中...
powershell -Command "Expand-Archive -Path '%PY_ZIP%' -DestinationPath '%DIST%\python' -Force"
del %PY_ZIP%

:: .pthを編集してsite-packagesを有効化
echo [3/5] Pythonパスを設定中...
powershell -Command ^
  "$pth = Get-Item '%DIST%\python\python3*.pth' | Select-Object -First 1;" ^
  "(Get-Content $pth.FullName) -replace '#import site','import site' | Set-Content $pth.FullName;" ^
  "Add-Content $pth.FullName 'Lib\site-packages'"

:: pipをインストール
powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get-pip.py' -UseBasicParsing"
%DIST%\python\python.exe get-pip.py --no-warn-script-location -q
del get-pip.py

:: 依存パッケージをインストール
echo [4/5] パッケージをインストール中...
%DIST%\python\python.exe -m pip install ^
  openai openpyxl python-docx rich json-repair ^
  --target %DIST%\python\Lib\site-packages ^
  --no-warn-script-location -q

:: アプリファイルをコピー
echo [5/5] アプリファイルをコピー中...
copy /y app.py      %DIST%\
copy /y engine.py   %DIST%\
copy /y app_config.py %DIST%\

:: ランチャーを作成
(
  echo @echo off
  echo cd /d "%%~dp0"
  echo set PYTHONPATH=%%~dp0
  echo python\python.exe app.py %%*
  echo if errorlevel 1 pause
) > %DIST%\run.bat

echo.
echo ========================================
echo  完了: %DIST%\
echo  run.bat をダブルクリックして起動
echo ========================================
echo.
pause
