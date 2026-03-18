@echo off
echo ===================================================
echo     NextOffice - Git Auto Update Script
echo ===================================================
echo.
echo 1. Adding all changes...
git add .
echo.
echo 2. Committing changes...
git commit -m "Auto update from bat script"
echo.
echo 3. Pushing to GitHub...
git push
echo.
echo ===================================================
echo     Update Successful! Check your GitHub page.
echo ===================================================
pause
