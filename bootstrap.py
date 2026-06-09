#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 쇼츠 편집기 부트스트랩 (exe 진입점)
# - 켤 때 웹(GitHub)에서 최신 app.py를 받아 실행 = OTA 자동 업데이트
# - 인터넷이 없으면 마지막 캐시 또는 내장 app.py로 실행
# - ffmpeg/폰트는 exe에 내장(_MEIPASS)되어 무설치로 어디서든 동작
import os, sys, urllib.request

# app.py는 아래에서 동적 로드(exec)되므로, PyInstaller가 app.py의 의존성을
# 분석하지 못한다. exe 빌드 시 이 모듈들이 번들에 포함되도록 미리 임포트한다.
import sqlite3, json, threading, webbrowser, glob, tempfile, datetime, time, re, subprocess, shutil
import http.server, urllib.parse
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    pass
try:
    import ctypes
except Exception:
    pass

APP_URL = "https://raw.githubusercontent.com/breezebsy/shorts-editor/main/app.py"

if getattr(sys, "frozen", False):
    EXE_DIR = os.path.dirname(sys.executable)
else:
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))
cache = os.path.join(EXE_DIR, "_app_cache.py")

# 1) 최신 app.py 다운로드 (실패해도 무시하고 진행)
try:
    req = urllib.request.Request(APP_URL, headers={"Cache-Control": "no-cache", "User-Agent": "shorts-editor"})
    data = urllib.request.urlopen(req, timeout=10).read()
    if data and b"def main" in data and b"ThreadingHTTPServer" in data:
        with open(cache, "wb") as f:
            f.write(data)
except Exception:
    pass

# 2) 실행할 소스 선택: 다운로드 캐시 > 내장 fallback
src = cache if os.path.exists(cache) else os.path.join(getattr(sys, "_MEIPASS", EXE_DIR), "app.py")
try:
    code = open(src, encoding="utf-8").read()
except Exception as e:
    input(f"app.py를 불러올 수 없습니다: {e}\n엔터로 종료...")
    sys.exit(1)

# 3) app.py를 메인으로 실행 (frozen이면 RUN_DIR=exe폴더, ffmpeg/폰트는 _MEIPASS)
g = {"__name__": "__main__", "__file__": sys.executable}
exec(compile(code, src, "exec"), g)
