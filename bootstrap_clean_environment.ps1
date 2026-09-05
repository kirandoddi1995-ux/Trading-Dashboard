$ErrorActionPreference = "Stop"

py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest pip-audit
& .\.venv\Scripts\python.exe environment_preflight.py --strict
& .\.venv\Scripts\python.exe -m pytest -q
& .\.venv\Scripts\python.exe deployment_canary.py
