@echo off
REM docs/index.html 굽기 — examples\examples.json 의 예제를 내장한다. 예제 형상을 다시 만들려면 먼저 python tools\make_examples.py
cd /d "%~dp0"
python tools\build_viewer.py tools\viewer_template.html docs\index.html examples\examples.json
