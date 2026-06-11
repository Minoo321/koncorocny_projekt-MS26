@echo off
echo ==========================================
echo  Spustanie Flask aplikacie (automaticky)
echo ==========================================
echo.

:: Presun do priecinka so suborom
cd /d "%~dp0"

:: Vytvor virtualne prostredie, ak neexistuje
if not exist ".venv\Scripts\activate.bat" (
    echo Vytvaram virtualne prostredie...
    py -3 -m venv .venv
)

:: Aktivuj virtualne prostredie
echo Aktivujem virtualne prostredie...
call ".venv\Scripts\activate.bat"

:: Upgrade pip
echo Aktualizujem pip...
python -m pip install --upgrade pip >nul

:: Kontrola balickov
echo Kontrolujem potrebne balicky...
python -m pip show flask >nul 2>&1 || python -m pip install flask
python -m pip show flask-wtf >nul 2>&1 || python -m pip install flask-wtf
python -m pip show flask-sqlalchemy >nul 2>&1 || python -m pip install flask-sqlalchemy
pip show email_validator >nul 2>&1 || pip install email_validator
pip show flask-login >nul 2>&1 || pip install flask_login
pip show requests >nul 2>&1 || pip install requests
pip show tzdata >nul 2>&1 || pip install tzdata

:: API kluc pre football-data.org (nepovinne - bez neho bezi demo rezim)
set FOOTBALL_DATA_API_KEY=5ddada2b97784f45b1bf654373e14e7b

:: Spustenie Flask aplikacie
echo.
echo ==========================================
echo Spustam Flask aplikaciu...
echo ==========================================
echo.

set FLASK_APP=main.py
set FLASK_ENV=development

python -m flask run --debug

:: Deaktivuj venv
call deactivate

echo.
echo ==========================================
echo Flask server bol ukonceny.
echo Stlac lubovolnu klavesu pre zatvorenie okna.
echo ==========================================
pause
