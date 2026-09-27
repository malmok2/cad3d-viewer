#!/bin/sh
# docs/index.html 굽기 (macOS · Linux) — build.cmd 와 같다. 예제 형상을 다시 만들려면 먼저 python3 tools/make_examples.py
cd "$(dirname "$0")" && python3 tools/build_viewer.py tools/viewer_template.html docs/index.html examples/examples.json
