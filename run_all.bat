@echo off
setlocal enabledelayedexpansion
title Open-Source Software Discovery Engine - One-Click Launcher

echo ==============================================================================
echo        OPEN-SOURCE SOFTWARE DISCOVERY ENGINE (MVP RUNNER)
echo ==============================================================================
echo.

cd /d "%~dp0"

:: 1. Verify Python & Virtual Environment
echo [1/5] Checking Python Virtual Environment...
if not exist "backend\venv\Scripts\python.exe" (
    echo [!] Virtual environment not found in backend\venv. Creating one...
    python -m venv backend\venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment. Ensure Python 3.12+ is installed and on PATH.
        pause
        exit /b 1
    )
    echo [*] Installing backend dependencies...
    backend\venv\Scripts\pip install -r backend\requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install backend dependencies.
        pause
        exit /b 1
    )
) else (
    echo [OK] Virtual environment detected at backend\venv.
)

:: 2. Database Initialization and Seeding
echo.
echo [2/5] Initializing Database and Seeding Catalog (51 verified apps)...
backend\venv\Scripts\python.exe -c "from app.database import Base, engine, SessionLocal; from app.services.taxonomy import seed_taxonomy, seed_catalog; Base.metadata.create_all(bind=engine); db=SessionLocal(); seed_taxonomy(db); seed_catalog(db); db.close(); print('[OK] Database and catalog ready.')"
if errorlevel 1 (
    echo [ERROR] Database initialization failed.
    pause
    exit /b 1
)

:: 3. Execute Verification Test Suite
echo.
echo [3/5] Running Automated Audit Test Suite (Hybrid Search, Evaluation, Security)...
pushd backend
venv\Scripts\pytest -v
if errorlevel 1 (
    echo [!] Warning: Some tests failed or returned non-zero code. Proceeding with launch...
) else (
    echo [OK] All tests passed.
)
popd

:: 4. Verify Frontend Dependencies
echo.
echo [4/5] Checking Frontend Dependencies...
if not exist "frontend\node_modules" (
    echo [*] node_modules not found in frontend. Running npm install...
    pushd frontend
    call npm install
    popd
) else (
    echo [OK] Frontend dependencies detected.
)

:: 5. Launch Backend & Frontend Services
echo.
echo [5/5] Launching Backend & Frontend Servers...

echo [*] Starting FastAPI Backend on http://127.0.0.1:8000 ...
start "OSS Discovery Engine - Backend (Port 8000)" cmd /k "cd /d %~dp0backend && venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload"

echo [*] Starting Vite Frontend on http://127.0.0.1:5173 ...
start "OSS Discovery Engine - Frontend (Port 5173)" cmd /k "cd /d %~dp0frontend && npm run dev -- --host 127.0.0.1 --port 5173"

:: Wait 3 seconds for services to bind
timeout /t 3 /nobreak >nul

:: Open browser
echo [*] Opening application in default browser...
start http://localhost:5173

echo.
echo ==============================================================================
echo [SUCCESS] Open-Source Software Discovery Engine is now running!
echo ==============================================================================
echo  - Frontend Web App:     http://localhost:5173
echo  - Backend API:          http://127.0.0.1:8000
echo  - Interactive Swagger:  http://127.0.0.1:8000/docs
echo  - Ops Health Check:     http://127.0.0.1:8000/api/v1/health
echo  - Ops Status Dashboard: http://127.0.0.1:8000/api/v1/ops/status
echo.
echo To stop the servers, simply close the respective terminal windows.
echo ==============================================================================
echo.
pause
