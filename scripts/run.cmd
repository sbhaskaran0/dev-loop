@echo off
rem Scheduler wrapper for the daily dev loop. Self-locating: works from any
rem clone location. The scheduled console is cp1252 — force UTF-8 for Python
rem and keep orchestrator console output ASCII.
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
python -m orchestrator --project job-applier >> runs\scheduler.log 2>&1
