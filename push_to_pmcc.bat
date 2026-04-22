@echo off
chcp 65001 >nul
echo =========================================
echo 🚀 Push to PMCC Repository
echo =========================================
echo.

:: מעבר לתיקיית הפרויקט
cd /d "%~dp0"

:: בדיקה אם Git מאותחל, אם לא - מאתחל
if not exist .git (
    echo [!] Initializing Git...
    git init
)

:: בדיקה אם ה-Remote של PMCC מוגדר, אם לא - מוסיף אותו
git remote | findstr /C:"origin" >nul
if %errorlevel% neq 0 (
    echo [1/4] Adding Remote...
    git remote add origin https://github.com/y0548476763-design/PMCC.git
)

echo [2/4] Adding all files...
git add .

echo [3/4] Committing...
set msg="Update PMCC: %date% %time%"
git commit -m %msg%

echo [4/4] Pushing to GitHub (PMCC)...
:: דחיפה לענף main (אם אצלך זה master, שנה ל-master)
git push origin main

echo.
echo =========================================
echo ✅ PMCC Updated Successfully!
echo =========================================
pause