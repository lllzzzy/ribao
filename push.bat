@echo off
chcp 65001 >nul
echo 正在向 GitHub (lllzzzy/ribao) 推送代码...
echo.

cd /d "%~dp0"
git remote set-url origin https://github.com/lllzzzy/ribao.git
git push -u origin main

echo.
if %ERRORLEVEL% EQU 0 (
    echo ========================================================
    echo 推送成功！代码已同步至 https://github.com/lllzzzy/ribao
    echo ========================================================
) else (
    echo ========================================================
    echo 推送未完成，请检查是否在弹出的浏览器中完成了 GitHub 登录授权。
    echo ========================================================
)
echo.
pause
