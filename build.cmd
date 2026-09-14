@echo off
REM docs/index.html 굽기 — 기본 예제(PCHE 70deg zigzag)를 내장한다. 빈 뷰어를 원하면 STL 인자 두 개를 뺀다.
cd /d "%~dp0"
python tools\build_viewer.py tools\viewer_template.html docs\index.html "PCHE_70deg_AirTap=examples\PCHE_70deg_AirTap.stl" "PCHE_70deg_recovered=examples\PCHE_70deg_recovered.stl"