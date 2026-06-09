#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 월천식 쇼츠 자동 편집기 (포터블 v3) — 윈도우 .exe / 맥 공용
# 미러·확대·채도·HDR·속도·코너로고가리기·채널명자막(+선택 BGM)
# - exe(PyInstaller)로 빌드되면 ffmpeg/폰트를 내부에서 사용
# - 원본영상/편집완료 등은 실행파일 위치에서 위로 올라가며 자동 탐색
import os, sys, subprocess, glob, tempfile, re, sqlite3, time, datetime, random

# 윈도우 콘솔에서 한글이 깨지지 않게 UTF-8로 강제
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None

W, H = 1080, 1920
FROZEN = getattr(sys, "frozen", False)
RUN_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
BUNDLE  = getattr(sys, "_MEIPASS", RUN_DIR)  # exe 내부 임시폴더(빌드시 동봉한 ffmpeg/폰트)

def find_ffmpeg():
    names = ["ffmpeg.exe", "ffmpeg"] if sys.platform == "win32" else ["ffmpeg"]
    for d in [BUNDLE, RUN_DIR, os.path.join(RUN_DIR, "_bin_win")]:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return "ffmpeg"  # PATH

FFMPEG = find_ffmpeg()

def find_font():
    cands = [
        os.path.join(BUNDLE, "font.ttf"), os.path.join(RUN_DIR, "font.ttf"),
        "C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/gulim.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None

FONT = find_font()

def find_base():
    # RUN_DIR에서 위로 올라가며 '원본영상' 폴더가 있는 디렉터리를 찾는다
    d = RUN_DIR
    for _ in range(6):
        if os.path.isdir(os.path.join(d, "원본영상")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return RUN_DIR if FROZEN else os.path.dirname(RUN_DIR)  # 폴백: exe는 자기폴더, 스크립트는 한 단계 위

BASE = find_base()
SRC_ROOT = os.path.join(BASE, "원본영상")
OUT_ROOT = os.path.join(BASE, "편집완료")
BGM_DIR  = os.path.join(BASE, "_BGM")
CH_FILE  = os.path.join(BASE, "_설정", "채널명.txt")

def ensure_dirs():
    # exe를 빈 폴더에 두고 실행해도 작동하도록 폴더 구조 자동 생성
    for p in [SRC_ROOT, OUT_ROOT, BGM_DIR, os.path.join(BASE, "_설정"),
              os.path.join(BASE, "템플릿"), os.path.join(BASE, "_효과음")]:
        try: os.makedirs(p, exist_ok=True)
        except Exception: pass
    if not os.path.exists(CH_FILE):
        try: open(CH_FILE, "w", encoding="utf-8").write("내채널")
        except Exception: pass

def latest_date_folder():
    subs = [d for d in glob.glob(os.path.join(SRC_ROOT, "*")) if os.path.isdir(d)]
    return sorted(subs)[-1] if subs else None

def channel_name():
    try:
        return open(CH_FILE, encoding="utf-8").read().strip() or "내채널"
    except Exception:
        return "내채널"

def make_caption_png(text, path, size=74, color=(255,255,255,255), bold=False, desc=""):
    # 글자 크기에 맞춰 캔버스를 만든다(자유 위치 배치를 위해)
    if len(color) == 3: color = (color[0], color[1], color[2], 255)
    meas = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    font = ImageFont.truetype(FONT, int(size)) if FONT else ImageFont.load_default()
    sw = 9 if bold else 4
    b1 = meas.textbbox((0, 0), text, font=font, stroke_width=sw)
    tw = b1[2]-b1[0]; th = b1[3]-b1[1]; pad = 44
    if desc:
        dfont = ImageFont.truetype(FONT, max(28, int(size*0.52))) if FONT else ImageFont.load_default()
        b2 = meas.textbbox((0, 0), desc, font=dfont, stroke_width=4)
        dw = b2[2]-b2[0]; dh = b2[3]-b2[1]; gap = 16
        Wc = max(tw, dw) + pad*2; Hc = th + gap + dh + pad
        img = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
        y0 = pad//2
        d.text(((Wc-tw)//2 - b1[0], y0 - b1[1]), text, font=font, fill=color, stroke_width=sw, stroke_fill=(0,0,0,220))
        d.text(((Wc-dw)//2 - b2[0], y0 + th + gap - b2[1]), desc, font=dfont, fill=(255,255,255,255), stroke_width=4, stroke_fill=(0,0,0,220))
    else:
        Wc = tw + pad*2; Hc = th + pad
        img = Image.new("RGBA", (Wc, Hc), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
        d.text(((Wc-tw)//2 - b1[0], (Hc-th)//2 - b1[1]), text, font=font, fill=color, stroke_width=sw, stroke_fill=(0,0,0,220))
    img.save(path)

def bgm_file():
    m = sorted(glob.glob(os.path.join(BGM_DIR, "*.mp3")) + glob.glob(os.path.join(BGM_DIR, "*.m4a")))
    return m[0] if m else None

def probe_dur(f):
    # 별도 ffprobe 없이 ffmpeg -i 로 길이 파싱
    try:
        r = subprocess.run([FFMPEG, "-i", f], capture_output=True, text=True)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", r.stderr)
        if m:
            h, mi, s = m.groups()
            return int(h)*3600 + int(mi)*60 + float(s)
    except Exception:
        pass
    return 0.0

def write_meta(out_dir, date, srcs):
    # 영상별 제목/설명/태그를 직접 붙여넣는 빈칸 양식 (제미나이 결과 입력용)
    p = os.path.join(out_dir, f"제목설명_{date}.txt")
    lines = [
        "="*56,
        f"  제목·설명 입력 양식 ({date})",
        "  제미나이 Gems로 만든 제목/설명/태그를 아래 빈칸에 붙여넣으세요.",
        "  (각 번호는 편집완료 영상 파일번호와 같음)",
        "="*56, "",
    ]
    for i, s in enumerate(srcs, 1):
        hint = os.path.splitext(os.path.basename(s))[0][:60]
        lines += [
            f"───── {date}_{i:02d}.mp4  (원본: {hint}) ─────",
            "[제목]",
            "",
            "[설명]",
            "※ 본 영상은 정보 제공·교육 목적으로 제작되었습니다.",
            "(쿠팡 파트너스 활동의 일환으로 일정액의 수수료를 제공받습니다.)",
            "제품: ",
            "",
            "[태그]",
            "",
            "",
        ]
    try:
        open(p, "w", encoding="utf-8").write("\n".join(lines))
        return p
    except Exception:
        return None

import json, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
HERE = RUN_DIR

DASHBOARD_HTML = r'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>쇼츠 자동편집</title>
<style>
  :root{ --blue:#0071e3; --blue2:#0077ed; --ink:#1d1d1f; --sub:#6e6e73; --bg:#f5f5f7; }
  *{ box-sizing:border-box; margin:0; padding:0; -webkit-font-smoothing:antialiased; }
  body{ font-family:-apple-system,"SF Pro Display",system-ui,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
    background:var(--bg); color:var(--ink); padding:32px 24px; }
  .wrap{ max-width:940px; margin:0 auto; }
  .top{ display:flex; align-items:center; justify-content:space-between; margin-bottom:22px; }
  h1{ font-size:26px; font-weight:700; letter-spacing:-.6px; }
  h1 .g{ color:var(--sub); font-weight:600; }
  .pill{ font-size:12.5px; color:var(--sub); background:#fff; padding:7px 14px; border-radius:980px;
    box-shadow:0 1px 4px rgba(0,0,0,.06); display:flex; gap:7px; align-items:center; }
  .dot{ width:7px; height:7px; border-radius:50%; background:#34c759; box-shadow:0 0 0 3px #34c75922; }
  .tabs{ display:inline-flex; background:#e8e8ed; border-radius:13px; padding:4px; gap:3px; }
  .tab{ padding:9px 22px; border-radius:10px; font-size:14.5px; font-weight:600; color:#5f5f66; text-decoration:none; transition:.2s; }
  .tab.active{ background:#fff; color:var(--ink); box-shadow:0 1px 4px rgba(0,0,0,.14); }
  .tab:hover:not(.active){ color:var(--ink); }
  .grid{ display:grid; grid-template-columns:1fr 1fr; gap:15px; }
  .card{ background:#fff; border-radius:20px; padding:18px; box-shadow:0 2px 14px rgba(0,0,0,.05);
    transition:transform .25s cubic-bezier(.4,0,.2,1), box-shadow .25s; }
  .card:hover{ transform:translateY(-2px); box-shadow:0 8px 26px rgba(0,0,0,.09); }
  .card.full{ grid-column:1/-1; }
  .lab{ font-size:12px; color:var(--sub); margin-bottom:10px; font-weight:600; }
  select,input[type=text]{ width:100%; background:var(--bg); border:none; color:var(--ink);
    padding:11px 13px; border-radius:11px; font-size:14px; outline:none; }
  .switches{ display:grid; grid-template-columns:repeat(3,1fr); gap:11px; }
  .sw{ display:flex; align-items:center; justify-content:space-between; gap:10px; background:var(--bg);
    padding:11px 14px; border-radius:13px; cursor:pointer; font-size:13.5px; font-weight:500;
    transition:background .2s, transform .12s; user-select:none; }
  .sw:active{ transform:scale(.97); }
  .sw.on{ background:#eaf3ff; color:#0a4ea3; }
  .tg{ width:42px; height:25px; border-radius:980px; background:#d1d1d6; position:relative; flex:0 0 42px; transition:background .25s; }
  .tg::after{ content:""; position:absolute; top:2px; left:2px; width:21px; height:21px; border-radius:50%;
    background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.25); transition:transform .25s cubic-bezier(.4,0,.2,1); }
  .sw.on .tg{ background:var(--blue); }
  .sw.on .tg::after{ transform:translateX(17px); }
  .srow{ display:flex; align-items:center; gap:14px; margin-top:12px; }
  .srow span{ font-size:13px; color:var(--sub); width:42px; }
  input[type=range]{ flex:1; -webkit-appearance:none; height:5px; border-radius:5px; background:#d8d8dd; outline:none; }
  input[type=range]::-webkit-slider-thumb{ -webkit-appearance:none; width:22px; height:22px; border-radius:50%;
    background:#fff; box-shadow:0 1px 4px rgba(0,0,0,.3); cursor:pointer; }
  .val{ font-size:13px; color:var(--blue); width:54px; text-align:right; font-weight:700; }
  .posgrid{ display:grid; grid-template-columns:repeat(3,38px); grid-template-rows:repeat(3,38px); gap:6px; }
  .pos{ background:var(--bg); border-radius:9px; cursor:pointer; transition:.15s; }
  .pos:hover{ background:#e3eefc; }
  .pos.on{ background:var(--blue); box-shadow:0 2px 8px #0071e355; }
  .capstyle{ display:flex; gap:10px; align-items:center; margin-top:10px; }
  .capstyle .sw{ flex:1; }
  .colbox{ display:flex; align-items:center; gap:8px; background:var(--bg); padding:9px 13px; border-radius:13px; font-size:13.5px; font-weight:500; cursor:pointer; }
  .colbox input[type=color]{ width:30px; height:30px; border:none; background:none; cursor:pointer; padding:0; }
  .go{ grid-column:1/-1; display:flex; gap:12px; }
  .btn{ flex:1; background:var(--blue); color:#fff; border:none; padding:16px; border-radius:14px;
    font-size:16px; font-weight:600; cursor:pointer; transition:transform .12s, background .2s; box-shadow:0 4px 16px #0071e333; }
  .btn:hover{ background:var(--blue2); } .btn:active{ transform:scale(.98); }
  .btn:disabled{ background:#aab; box-shadow:none; cursor:default; }
  .btn.sec{ flex:0 0 150px; background:#fff; color:var(--blue); box-shadow:0 2px 10px rgba(0,0,0,.06); }
  .bar{ height:8px; background:var(--bg); border-radius:6px; overflow:hidden; }
  .bar>i{ display:block; height:100%; width:0%; border-radius:6px; background:linear-gradient(90deg,#0071e3,#5ac8fa); transition:width .4s; }
  .log{ margin-top:12px; background:var(--bg); border-radius:12px; padding:13px; font-family:"SF Mono",Menlo,monospace;
    font-size:12px; color:#48484a; height:120px; overflow:auto; line-height:1.8; white-space:pre-wrap; }
  .log b{ color:#34c759; }
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="tabs">
      <a class="tab active" href="/">🎬 대량 편집</a>
      <a class="tab" href="/single">✂ 개별 편집</a>
      <a class="tab" href="/digg">💀 도굴</a>
      <a class="tab" href="/settings">⚙ 설정</a>
    </div>
    <div style="display:flex;gap:10px;align-items:center">
      <div class="pill"><span class="dot"></span><span id="ver">v2.0</span> · 자동업데이트 켜짐</div>
      <a href="#" id="quit" style="font-size:13px;color:#c0392b;text-decoration:none;background:#fff;padding:8px 13px;border-radius:980px;box-shadow:0 1px 4px rgba(0,0,0,.06);font-weight:600">⏻ 종료</a>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="lab">원본 영상 폴더 (날짜)</div>
      <select id="date"></select>
      <div class="lab" style="margin-top:8px" id="cnt">영상 0개</div>
      <div class="lab" style="margin-top:14px">템플릿 (인스타 프레임)</div>
      <select id="tpl"></select>
    </div>
    <div class="card">
      <div class="lab">채널명 자막</div>
      <input type="text" id="ch" value="">
      <div class="srow" style="margin-top:12px"><span>크기</span><input type="range" min="40" max="120" value="74" id="cz"><div class="val" id="czv">74</div></div>
      <div class="capstyle">
        <div class="sw" id="cbold">굵게<div class="tg"></div></div>
        <label class="colbox">색상<input type="color" id="ccol" value="#ffffff"></label>
      </div>
      <div class="srow" style="margin-top:8px"><span>자막 ↔</span><input type="range" min="0" max="100" value="50" id="capx"><div class="val" id="capxv">50%</div></div>
      <div class="srow"><span>자막 ↕</span><input type="range" min="0" max="100" value="88" id="capy"><div class="val" id="capyv">88%</div></div>
      <div class="lab" style="margin-top:14px">배경음악 (BGM)</div>
      <select id="bgm"></select>
      <div class="lab" style="margin-top:12px">인트로 효과음 (두둥)</div>
      <select id="sfx"></select>
      <div class="lab" style="margin-top:12px">설명 자막 · 둘째 줄 (선택)</div>
      <input type="text" id="desc" value="" placeholder="예: 이건 진짜 신기함">
    </div>

    <div class="card full">
      <div class="lab">적용할 변환 · 탭하여 켜고 끄기</div>
      <div class="switches" id="sw">
        <div class="sw on" data-k="mirror">좌우반전<div class="tg"></div></div>
        <div class="sw on" data-k="zoom_on">확대 크롭<div class="tg"></div></div>
        <div class="sw on" data-k="hdr">채도·HDR<div class="tg"></div></div>
        <div class="sw on" data-k="sharp">선명도<div class="tg"></div></div>
        <div class="sw on" data-k="logo">로고 가리기<div class="tg"></div></div>
        <div class="sw on" data-k="caption">채널명 자막<div class="tg"></div></div>
        <div class="sw" data-k="trim">앞뒤 트림<div class="tg"></div></div>
        <div class="sw" data-k="cap_anim">자막 등장<div class="tg"></div></div>
        <div class="sw" data-k="mask">마스크 블러<div class="tg"></div></div>
      </div>
      <div class="srow"><span>확대</span><input type="range" min="100" max="200" value="113" id="z"><div class="val" id="zv">113%</div></div>
      <div class="srow"><span>속도</span><input type="range" min="100" max="150" value="108" id="s"><div class="val" id="sv">1.08×</div></div>
      <div style="display:flex; gap:28px; margin-top:16px; flex-wrap:wrap; align-items:flex-start">
        <div>
          <div class="lab">확대 기준 위치 · <b id="posname" style="color:var(--blue)">중앙</b></div>
          <div class="posgrid" id="pos">
            <div class="pos" data-x="0" data-y="0"></div>
            <div class="pos" data-x="0.5" data-y="0"></div>
            <div class="pos" data-x="1" data-y="0"></div>
            <div class="pos" data-x="0" data-y="0.5"></div>
            <div class="pos on" data-x="0.5" data-y="0.5"></div>
            <div class="pos" data-x="1" data-y="0.5"></div>
            <div class="pos" data-x="0" data-y="1"></div>
            <div class="pos" data-x="0.5" data-y="1"></div>
            <div class="pos" data-x="1" data-y="1"></div>
          </div>
        </div>
        <div style="flex:1; min-width:340px">
          <div class="lab">마스크 블러 위치·크기 (원본 글씨 가리기 · 👁미리보기로 맞추기)</div>
          <div class="srow" style="margin-top:6px"><span>가로</span><input type="range" min="0" max="100" value="50" id="maskx"><div class="val" id="maskxv">50%</div></div>
          <div class="srow"><span>세로</span><input type="range" min="0" max="100" value="100" id="masky"><div class="val" id="maskyv">100%</div></div>
          <div class="srow"><span>폭</span><input type="range" min="150" max="1080" value="720" id="maskw"><div class="val" id="maskwv">720</div></div>
          <div class="srow"><span>높이</span><input type="range" min="60" max="600" value="190" id="maskh"><div class="val" id="maskhv">190</div></div>
        </div>
      </div>
    </div>

    <div class="go">
      <button class="btn" id="run">▶  편집 시작</button>
      <button class="btn sec" id="prev">👁 미리보기</button>
      <button class="btn sec" id="open">결과 폴더 열기</button>
    </div>

    <div class="card full">
      <div class="lab" id="ptit">진행 상황</div>
      <img id="previmg" style="display:none;width:300px;border-radius:14px;margin-bottom:12px;box-shadow:0 2px 12px rgba(0,0,0,.18)">
      <div class="bar"><i id="pbar"></i></div>
      <div class="log" id="log">대기 중…</div>
    </div>
  </div>
</div>
<script>
const $=s=>document.querySelector(s);
let polling=null;
async function load(){
  const r=await fetch('/api/state'); const d=await r.json();
  $('#ver').textContent='v'+d.version;
  $('#date').innerHTML=d.dates.map(x=>`<option>${x}</option>`).join('')||'<option>(없음)</option>';
  $('#ch').value=d.channel;
  $('#bgm').innerHTML=d.bgms.map(x=>`<option>${x}</option>`).join('');
  $('#tpl').innerHTML=(d.templates||['(템플릿 없음)']).map(x=>`<option>${x}</option>`).join('');
  $('#sfx').innerHTML=(d.sfx||['(효과음 없음)']).map(x=>`<option>${x}</option>`).join('');
  $('#cnt').textContent='영상 '+d.count+'개';
}
$('#date').onchange=async()=>{ const r=await fetch('/api/count?date='+encodeURIComponent($('#date').value));
  const d=await r.json(); $('#cnt').textContent='영상 '+d.count+'개'; };
document.querySelectorAll('#sw .sw').forEach(el=>el.onclick=()=>el.classList.toggle('on'));
z.oninput=()=>zv.textContent=z.value+'%';
s.oninput=()=>sv.textContent=(s.value/100).toFixed(2)+'×';
cz.oninput=()=>czv.textContent=cz.value;
capx.oninput=()=>capxv.textContent=capx.value+'%';
capy.oninput=()=>capyv.textContent=capy.value+'%';
maskw.oninput=()=>maskwv.textContent=maskw.value;
maskh.oninput=()=>maskhv.textContent=maskh.value;
maskx.oninput=()=>maskxv.textContent=maskx.value+'%';
masky.oninput=()=>maskyv.textContent=masky.value+'%';
cbold.onclick=()=>cbold.classList.toggle('on');
let pos={x:0.5,y:0.5};
const POSNAME={'0,0':'좌상단','0.5,0':'상단','1,0':'우상단','0,0.5':'좌측','0.5,0.5':'중앙','1,0.5':'우측','0,1':'좌하단','0.5,1':'하단','1,1':'우하단'};
document.querySelectorAll('#pos .pos').forEach(el=>{
  el.title=POSNAME[el.dataset.x+','+el.dataset.y];
  el.onclick=()=>{
    document.querySelectorAll('#pos .pos').forEach(p=>p.classList.remove('on'));
    el.classList.add('on'); pos={x:+el.dataset.x, y:+el.dataset.y};
    document.querySelector('#posname').textContent=POSNAME[el.dataset.x+','+el.dataset.y];
  };
});
function opts(){ const o={zoom:+z.value, speed:+s.value, zx:pos.x, zy:pos.y,
    cap_size:+cz.value, cap_color:ccol.value, cap_bold:cbold.classList.contains('on'), cap_x:capx.value/100, cap_y:capy.value/100,
    template:tpl.value, sfx:$('#sfx').value, desc:$('#desc').value};
  document.querySelectorAll('#sw .sw').forEach(el=>o[el.dataset.k]=el.classList.contains('on'));
  o.mask_px=maskx.value/100; o.mask_py=masky.value/100; o.mask_w=+maskw.value; o.mask_h=+maskh.value;
  return o; }
$('#run').onclick=async()=>{
  $('#run').disabled=true; $('#run').textContent='편집 중…'; $('#log').textContent='시작하는 중…';
  await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({date:$('#date').value, channel:$('#ch').value, bgm:$('#bgm').value, opts:opts()})});
  if(polling) clearInterval(polling);
  polling=setInterval(poll,800);
};
async function poll(){
  const r=await fetch('/api/progress'); const s=await r.json();
  const pct=s.total? Math.round(s.current/s.total*100):0;
  $('#pbar').style.width=pct+'%';
  $('#ptit').textContent=`진행 상황 · ${s.current} / ${s.total}`;
  $('#log').innerHTML=s.lines.slice().reverse().map(l=>l.replace('완료','<b>완료</b>')).join('\n');
  if(s.done && !s.running){ clearInterval(polling); $('#run').disabled=false; $('#run').textContent='▶  편집 시작'; }
}
$('#prev').onclick=async()=>{
  const b=$('#prev'); b.textContent='생성중…'; b.disabled=true;
  try{
    const r=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({date:$('#date').value, channel:$('#ch').value, opts:opts()})});
    const blob=await r.blob();
    if(blob.size>0){ const im=$('#previmg'); im.src=URL.createObjectURL(blob); im.style.display='block'; }
    else alert('미리보기 실패 (영상이 없는지 확인)');
  }catch(e){ alert('미리보기 오류'); }
  b.textContent='👁 미리보기'; b.disabled=false;
};
$('#open').onclick=()=>fetch('/api/open');
$('#quit').onclick=(e)=>{ e.preventDefault();
  if(confirm('프로그램을 종료할까요?')){ fetch('/api/shutdown').catch(()=>{});
    document.body.innerHTML='<div style="padding:80px;text-align:center;font-size:18px;color:#888">프로그램이 종료되었습니다.<br>이 브라우저 탭은 닫으셔도 됩니다.</div>'; } };
load();
</script>
</body>
</html>
'''

SINGLE_HTML = r'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>개별 편집</title>
<style>
  :root{ --blue:#0071e3; --blue2:#0077ed; --ink:#1d1d1f; --sub:#6e6e73; --bg:#f5f5f7; }
  *{ box-sizing:border-box; margin:0; padding:0; -webkit-font-smoothing:antialiased; }
  body{ font-family:-apple-system,"SF Pro Display",system-ui,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
    background:var(--bg); color:var(--ink); padding:30px 24px; }
  .wrap{ max-width:960px; margin:0 auto; }
  .top{ display:flex; align-items:center; justify-content:space-between; margin-bottom:20px; }
  h1{ font-size:24px; font-weight:700; letter-spacing:-.5px; }
  h1 .g{ color:var(--sub); font-weight:600; }
  a.link{ font-size:13px; color:var(--blue); text-decoration:none; background:#fff; padding:8px 14px; border-radius:980px; box-shadow:0 1px 4px rgba(0,0,0,.06); }
  .tabs{ display:inline-flex; background:#e8e8ed; border-radius:13px; padding:4px; gap:3px; }
  .tab{ padding:9px 22px; border-radius:10px; font-size:14.5px; font-weight:600; color:#5f5f66; text-decoration:none; transition:.2s; }
  .tab.active{ background:#fff; color:var(--ink); box-shadow:0 1px 4px rgba(0,0,0,.14); }
  .tab:hover:not(.active){ color:var(--ink); }
  .grid{ display:grid; grid-template-columns:1.2fr 1fr; gap:15px; align-items:start; }
  .card{ background:#fff; border-radius:18px; padding:16px; box-shadow:0 2px 14px rgba(0,0,0,.05); }
  .lab{ font-size:12px; color:var(--sub); margin-bottom:9px; font-weight:600; }
  select,input[type=text]{ width:100%; background:var(--bg); border:none; color:var(--ink); padding:10px 12px; border-radius:10px; font-size:13.5px; outline:none; }
  video{ width:100%; border-radius:14px; background:#000; margin-top:6px; }
  .tbar{ display:flex; gap:8px; margin-top:10px; }
  .btn{ background:var(--blue); color:#fff; border:none; padding:11px 14px; border-radius:11px; font-size:13.5px; font-weight:600; cursor:pointer; }
  .btn:active{ transform:scale(.97); } .btn.sec{ background:var(--bg); color:var(--blue); }
  .btn.full{ width:100%; padding:15px; font-size:15px; border-radius:13px; box-shadow:0 4px 16px #0071e333; }
  .cur{ font-size:12.5px; color:var(--sub); margin-top:8px; }
  .cur b{ color:var(--blue); }
  .seg{ display:flex; align-items:center; gap:8px; background:var(--bg); padding:9px 12px; border-radius:11px; margin-top:8px; font-size:13px; }
  .seg .n{ width:24px; height:24px; border-radius:7px; background:var(--blue); color:#fff; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; }
  .seg .t{ flex:1; }
  .seg button{ border:none; background:#fff; width:28px; height:28px; border-radius:8px; cursor:pointer; font-size:13px; }
  .switches{ display:grid; grid-template-columns:1fr 1fr; gap:9px; margin-top:6px; }
  .sw{ display:flex; align-items:center; justify-content:space-between; background:var(--bg); padding:9px 12px; border-radius:11px; cursor:pointer; font-size:13px; font-weight:500; user-select:none; }
  .sw.on{ background:#eaf3ff; color:#0a4ea3; }
  .tg{ width:38px; height:23px; border-radius:980px; background:#d1d1d6; position:relative; flex:0 0 38px; transition:.25s; }
  .tg::after{ content:""; position:absolute; top:2px; left:2px; width:19px; height:19px; border-radius:50%; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.25); transition:.25s; }
  .sw.on .tg{ background:var(--blue); } .sw.on .tg::after{ transform:translateX(15px); }
  .srow{ display:flex; align-items:center; gap:12px; margin-top:11px; }
  .srow span{ font-size:12.5px; color:var(--sub); width:42px; }
  input[type=range]{ flex:1; -webkit-appearance:none; height:5px; border-radius:5px; background:#d8d8dd; }
  input[type=range]::-webkit-slider-thumb{ -webkit-appearance:none; width:20px; height:20px; border-radius:50%; background:#fff; box-shadow:0 1px 4px rgba(0,0,0,.3); }
  .val{ font-size:12.5px; color:var(--blue); width:48px; text-align:right; font-weight:700; }
  .capstyle{ display:flex; gap:8px; align-items:center; margin-top:10px; }
  .capstyle .sw{ flex:1; }
  .colbox{ display:flex; align-items:center; gap:7px; background:var(--bg); padding:8px 11px; border-radius:11px; font-size:12.5px; font-weight:500; cursor:pointer; }
  .colbox input[type=color]{ width:28px; height:28px; border:none; background:none; cursor:pointer; padding:0; }
  .posgrid{ display:grid; grid-template-columns:repeat(3,34px); grid-template-rows:repeat(3,34px); gap:5px; }
  .pos{ background:var(--bg); border-radius:8px; cursor:pointer; transition:.15s; }
  .pos:hover{ background:#e3eefc; } .pos.on{ background:var(--blue); box-shadow:0 2px 8px #0071e355; }
  .msg{ margin-top:12px; font-size:13px; color:var(--sub); }
  .msg b{ color:#34c759; }
  .hint{ font-size:11.5px; color:#999; margin-top:6px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="tabs">
      <a class="tab" href="/">🎬 대량 편집</a>
      <a class="tab active" href="/single">✂ 개별 편집</a>
      <a class="tab" href="/digg">💀 도굴</a>
      <a class="tab" href="/settings">⚙ 설정</a>
    </div>
  </div>
  <div class="grid">
    <div class="card">
      <div class="lab">날짜 폴더</div>
      <select id="date"></select>
      <div class="lab" style="margin-top:10px">영상 선택</div>
      <select id="file"></select>
      <video id="vid" controls></video>
      <div class="tbar">
        <button class="btn sec" id="setin">⟜ 시작점</button>
        <button class="btn sec" id="setout">끝점 ⟝</button>
        <button class="btn" id="add">＋ 구간 추가</button>
      </div>
      <div class="tbar" style="margin-top:8px;align-items:center">
        <span style="font-size:12.5px;color:var(--sub)">자동 분할</span>
        <input type="number" id="seglen" value="3" min="1" max="10" style="width:56px;background:var(--bg);border:none;border-radius:10px;padding:8px;text-align:center;font-size:13px">
        <span style="font-size:12.5px;color:var(--sub)">초씩</span>
        <button class="btn sec" id="autosplit">⎚ 통째로 자동 분할</button>
      </div>
      <div class="cur">현재 구간: <b id="rin">–</b> ~ <b id="rout">–</b></div>
      <div class="hint">영상 재생/이동 후 [시작점]·[끝점] 누르고 [구간 추가]. 여러 구간을 넣고 순서를 바꾸면 "컷 순서 비틀기"가 됩니다.</div>
    </div>
    <div class="card">
      <div class="lab">자를 구간 (위→아래 순서대로 이어붙임)</div>
      <div id="segs"></div>
      <div class="lab" style="margin-top:16px">템플릿</div>
      <select id="tpl"></select>
      <div class="lab" style="margin-top:12px">채널명 자막</div>
      <input type="text" id="ch" value="">
      <div class="srow" style="margin-top:10px"><span>크기</span><input type="range" min="40" max="120" value="74" id="cz"><div class="val" id="czv">74</div></div>
      <div class="capstyle">
        <div class="sw" id="cbold">굵게<div class="tg"></div></div>
        <label class="colbox">색상<input type="color" id="ccol" value="#ffffff"></label>
      </div>
      <div class="srow" style="margin-top:8px"><span>자막 ↔</span><input type="range" min="0" max="100" value="50" id="capx"><div class="val" id="capxv">50%</div></div>
      <div class="srow"><span>자막 ↕</span><input type="range" min="0" max="100" value="88" id="capy"><div class="val" id="capyv">88%</div></div>
      <div class="lab" style="margin-top:12px">BGM / 효과음 / 설명자막</div>
      <select id="bgm"></select>
      <select id="sfx" style="margin-top:8px"></select>
      <input type="text" id="desc" value="" placeholder="설명 자막 둘째 줄 (선택)" style="margin-top:8px">
      <div class="switches" id="sw" style="margin-top:12px">
        <div class="sw on" data-k="mirror">좌우반전<div class="tg"></div></div>
        <div class="sw on" data-k="zoom_on">확대<div class="tg"></div></div>
        <div class="sw on" data-k="hdr">채도·HDR<div class="tg"></div></div>
        <div class="sw on" data-k="sharp">선명도<div class="tg"></div></div>
        <div class="sw on" data-k="logo">로고가리기<div class="tg"></div></div>
        <div class="sw on" data-k="caption">채널자막<div class="tg"></div></div>
        <div class="sw" data-k="trim">앞뒤트림<div class="tg"></div></div>
        <div class="sw" data-k="cap_anim">자막등장<div class="tg"></div></div>
        <div class="sw" data-k="mask">마스크블러<div class="tg"></div></div>
      </div>
      <div class="srow"><span>확대</span><input type="range" min="100" max="200" value="113" id="z"><div class="val" id="zv">113%</div></div>
      <div class="srow"><span>속도</span><input type="range" min="100" max="150" value="108" id="s"><div class="val" id="sv">1.08×</div></div>
      <div style="display:flex; gap:20px; margin-top:12px; flex-wrap:wrap; align-items:flex-start">
        <div>
          <div class="lab">확대 기준 · <b id="posname" style="color:var(--blue)">중앙</b></div>
          <div class="posgrid" id="pos">
            <div class="pos" data-x="0" data-y="0"></div><div class="pos" data-x="0.5" data-y="0"></div><div class="pos" data-x="1" data-y="0"></div>
            <div class="pos" data-x="0" data-y="0.5"></div><div class="pos on" data-x="0.5" data-y="0.5"></div><div class="pos" data-x="1" data-y="0.5"></div>
            <div class="pos" data-x="0" data-y="1"></div><div class="pos" data-x="0.5" data-y="1"></div><div class="pos" data-x="1" data-y="1"></div>
          </div>
        </div>
        <div style="flex:1; min-width:250px">
          <div class="lab">마스크 블러 위치·크기</div>
          <div class="srow" style="margin-top:6px"><span>가로</span><input type="range" min="0" max="100" value="50" id="maskx"><div class="val" id="maskxv">50%</div></div>
          <div class="srow"><span>세로</span><input type="range" min="0" max="100" value="100" id="masky"><div class="val" id="maskyv">100%</div></div>
          <div class="srow"><span>폭</span><input type="range" min="150" max="1080" value="720" id="maskw"><div class="val" id="maskwv">720</div></div>
          <div class="srow"><span>높이</span><input type="range" min="60" max="600" value="190" id="maskh"><div class="val" id="maskhv">190</div></div>
        </div>
      </div>
      <button class="btn full" id="prev" style="margin-top:14px;background:var(--bg);color:var(--blue);box-shadow:none">👁 미리보기</button>
      <img id="previmg" style="display:none;width:280px;border-radius:12px;margin-top:10px;box-shadow:0 2px 12px rgba(0,0,0,.18)">
      <button class="btn full" id="make" style="margin-top:12px">✓ 이 구성으로 만들기</button>
      <div class="msg" id="msg"></div>
    </div>
  </div>
</div>
<script>
const $=s=>document.querySelector(s);
const vid=$('#vid'); let segs=[]; let rin=null, rout=null;
function fmt(t){ if(t==null) return '–'; t=Math.max(0,t); const m=Math.floor(t/60), s=(t%60); return m+':'+s.toFixed(1).padStart(4,'0'); }
async function init(){
  const st=await (await fetch('/api/state')).json();
  $('#date').innerHTML=st.dates.map(x=>`<option>${x}</option>`).join('');
  $('#tpl').innerHTML=(st.templates||['(템플릿 없음)']).map(x=>`<option>${x}</option>`).join('');
  $('#bgm').innerHTML=(st.bgms||['(원본 소리 사용)']).map(x=>`<option>${x}</option>`).join('');
  $('#sfx').innerHTML=(st.sfx||['(효과음 없음)']).map(x=>`<option>${x}</option>`).join('');
  $('#ch').value=st.channel||'';
  await loadFiles();
}
async function loadFiles(){
  const d=$('#date').value;
  const r=await (await fetch('/api/files?date='+encodeURIComponent(d))).json();
  $('#file').innerHTML=(r.files||[]).map(x=>`<option>${x}</option>`).join('');
  loadVideo();
}
function loadVideo(){
  const d=$('#date').value, f=$('#file').value;
  if(!f) return;
  vid.src='/video?date='+encodeURIComponent(d)+'&file='+encodeURIComponent(f);
  segs=[]; rin=rout=null; render(); upd();
}
$('#date').onchange=loadFiles;
$('#file').onchange=loadVideo;
$('#setin').onclick=()=>{ rin=vid.currentTime; upd(); };
$('#setout').onclick=()=>{ rout=vid.currentTime; upd(); };
function upd(){ $('#rin').textContent=fmt(rin); $('#rout').textContent=fmt(rout); }
$('#add').onclick=()=>{
  if(rin==null||rout==null||rout<=rin){ alert('시작점과 끝점을 먼저 지정하세요 (끝점이 시작점보다 뒤).'); return; }
  segs.push({start:+rin.toFixed(2), end:+rout.toFixed(2)}); rin=rout=null; upd(); render();
};
function render(){
  $('#segs').innerHTML=segs.map((s,i)=>`<div class="seg" style="flex-wrap:wrap"><div class="n">${i+1}</div>
    <div class="t">${fmt(s.start)} ~ ${fmt(s.end)} <span style="color:#aaa">(${(s.end-s.start).toFixed(1)}초)</span></div>
    <button onclick="mv(${i},-1)">↑</button><button onclick="mv(${i},1)">↓</button><button onclick="del(${i})">✕</button>
    <input value="${(s.text||'').replace(/"/g,'&quot;')}" placeholder="이 구간 자막 (선택 · 예: 1위)" oninput="segs[${i}].text=this.value" style="flex-basis:100%;margin-top:7px;background:#fff;border:none;border-radius:8px;padding:8px 11px;font-size:12.5px;outline:none"></div>`).join('')
    || '<div class="hint">아직 구간이 없어요. 위에서 구간을 추가하세요.</div>';
}
window.mv=(i,d)=>{ const j=i+d; if(j<0||j>=segs.length) return; [segs[i],segs[j]]=[segs[j],segs[i]]; render(); };
window.del=(i)=>{ segs.splice(i,1); render(); };
$('#autosplit').onclick=()=>{
  const dur=vid.duration;
  if(!dur||!isFinite(dur)){ alert('영상을 먼저 불러오세요'); return; }
  const len=Math.max(1,+$('#seglen').value||3); segs=[];
  for(let t=0;t<dur-0.3;t+=len){ segs.push({start:+t.toFixed(2), end:+Math.min(dur,t+len).toFixed(2)}); }
  render();
};
z.oninput=()=>zv.textContent=z.value+'%';
s.oninput=()=>sv.textContent=(s.value/100).toFixed(2)+'×';
cz.oninput=()=>czv.textContent=cz.value;
capx.oninput=()=>capxv.textContent=capx.value+'%';
capy.oninput=()=>capyv.textContent=capy.value+'%';
maskw.oninput=()=>maskwv.textContent=maskw.value;
maskh.oninput=()=>maskhv.textContent=maskh.value;
maskx.oninput=()=>maskxv.textContent=maskx.value+'%';
masky.oninput=()=>maskyv.textContent=masky.value+'%';
cbold.onclick=()=>cbold.classList.toggle('on');
document.querySelectorAll('#sw .sw').forEach(el=>el.onclick=()=>el.classList.toggle('on'));
let pos={x:0.5,y:0.5};
const POSNAME={'0,0':'좌상단','0.5,0':'상단','1,0':'우상단','0,0.5':'좌측','0.5,0.5':'중앙','1,0.5':'우측','0,1':'좌하단','0.5,1':'하단','1,1':'우하단'};
document.querySelectorAll('#pos .pos').forEach(el=>{ el.title=POSNAME[el.dataset.x+','+el.dataset.y];
  el.onclick=()=>{ document.querySelectorAll('#pos .pos').forEach(p=>p.classList.remove('on')); el.classList.add('on'); pos={x:+el.dataset.x,y:+el.dataset.y}; $('#posname').textContent=POSNAME[el.dataset.x+','+el.dataset.y]; }; });
function opts(){ const o={zoom:+z.value, speed:+s.value, zx:pos.x, zy:pos.y,
    cap_size:+cz.value, cap_color:ccol.value, cap_bold:cbold.classList.contains('on'), cap_x:capx.value/100, cap_y:capy.value/100,
    template:$('#tpl').value, sfx:$('#sfx').value, desc:$('#desc').value};
  document.querySelectorAll('#sw .sw').forEach(el=>o[el.dataset.k]=el.classList.contains('on'));
  o.mask_px=maskx.value/100; o.mask_py=masky.value/100; o.mask_w=+maskw.value; o.mask_h=+maskh.value;
  return o; }
$('#prev').onclick=async()=>{
  if(!$('#file').value){ alert('영상을 먼저 선택하세요'); return; }
  const b=$('#prev'); b.textContent='생성중…'; b.disabled=true;
  try{
    const r=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({date:$('#date').value, file:$('#file').value, channel:$('#ch').value, opts:opts()})});
    const blob=await r.blob();
    if(blob.size>0){ const im=$('#previmg'); im.src=URL.createObjectURL(blob); im.style.display='block'; }
    else alert('미리보기 실패');
  }catch(e){ alert('미리보기 오류'); }
  b.textContent='👁 미리보기'; b.disabled=false;
};
$('#make').onclick=async()=>{
  if(!segs.length){ alert('구간을 1개 이상 추가하세요.'); return; }
  $('#make').disabled=true; $('#msg').textContent='만드는 중…';
  const r=await (await fetch('/api/trim',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({date:$('#date').value, file:$('#file').value, segments:segs, channel:$('#ch').value, bgm:$('#bgm').value, opts:opts()})})).json();
  $('#make').disabled=false;
  $('#msg').innerHTML = r.ok ? `<b>완료!</b> 편집완료/${$('#date').value}/개별/ → ${r.out} (${r.parts}구간)` : '실패: '+(r.msg||'');
};
init();
</script>
</body>
</html>
'''

VERSION = "2.4"
STATE = {"running": False, "current": 0, "total": 0, "lines": [], "done": False, "date": ""}

def hexrgb(h):
    h = str(h).lstrip("#")
    try: return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), 255)
    except Exception: return (255,255,255,255)

def date_folders():
    subs = [os.path.basename(d) for d in glob.glob(os.path.join(SRC_ROOT, "*")) if os.path.isdir(d)]
    return sorted(subs, reverse=True)

def count_videos(date):
    return len(glob.glob(os.path.join(SRC_ROOT, date, "*.mp4"))) if date else 0

def bgm_list():
    out = ["(원본 소리 사용)"]
    out += [os.path.basename(p) for p in sorted(glob.glob(os.path.join(BGM_DIR, "*.mp3")) + glob.glob(os.path.join(BGM_DIR, "*.m4a")))]
    return out

def sfx_list():
    d = os.path.join(BASE, "_효과음")
    out = ["(효과음 없음)"]
    out += [os.path.basename(p) for p in sorted(glob.glob(os.path.join(d, "*.mp3")) + glob.glob(os.path.join(d, "*.wav")))]
    return out

def resolve_sfx(opts):
    sname = opts.get("sfx")
    if sname and not str(sname).startswith("("):
        sp = os.path.join(BASE, "_효과음", sname)
        if os.path.exists(sp): return sp
    return None

def template_window(path):
    try:
        im = Image.open(path).convert("RGBA")
        a = im.split()[3].point(lambda v: 255 if v < 30 else 0)
        bbox = a.getbbox()
        if not bbox: return None
        x0, y0, x1, y1 = bbox
        return (x0 - x0 % 2, y0 - y0 % 2, (x1-x0)//2*2, (y1-y0)//2*2)
    except Exception:
        return None

def template_list():
    d = os.path.join(BASE, "템플릿")
    out = ["(템플릿 없음)"]
    out += [os.path.basename(p) for p in sorted(glob.glob(os.path.join(d, "*.png")))]
    return out

def mask_region(opts):
    mw = min(1080, max(60, int(opts.get("mask_w", 720))))
    mh = min(900, max(40, int(opts.get("mask_h", 190))))
    fx = float(opts.get("mask_px", 0.5)); fy = float(opts.get("mask_py", 1.0))
    mx = int((1080-mw)*fx); my = int((1920-mh)*fy)
    return mx-mx%2, my-my%2, mw-mw%2, mh-mh%2

def build_vf(opts, spd, tpl_win=None):
    ev = opts.get("evade", False)  # 일치율 회피: 매 렌더마다 미세값을 random하게(고정값=패턴 감지)
    fl = []
    if opts.get("mirror", True): fl.append("hflip")
    z = max(100, int(opts.get("zoom", 113))) / 100.0
    if ev: z = round(max(1.04, z + random.uniform(-0.02, 0.03)), 3)
    if opts.get("zoom_on", True) and z > 1.0:
        fx = min(1.0, max(0.0, float(opts.get("zx", 0.5)) + (random.uniform(-0.06, 0.06) if ev else 0)))
        fy = min(1.0, max(0.0, float(opts.get("zy", 0.5)) + (random.uniform(-0.06, 0.06) if ev else 0)))
        fl.append(f"scale=1080*{z}:1920*{z}:force_original_aspect_ratio=increase")
        fl.append(f"crop=1080:1920:(in_w-1080)*{fx}:(in_h-1920)*{fy}")
    if opts.get("hdr", True):
        if ev:
            sat = round(random.uniform(1.28, 1.42), 3); con = round(random.uniform(1.06, 1.16), 3); bri = round(random.uniform(-0.01, 0.04), 3)
        else:
            sat, con, bri = 1.35, 1.12, 0.02
        fl.append(f"eq=saturation={sat}:contrast={con}:brightness={bri}")
    if opts.get("sharp", True): fl.append("unsharp=5:5:0.8")
    if ev: fl.append(f"noise=alls={random.randint(2,5)}:allf=t")
    if opts.get("trim", False): fl.append("trim=start=0.3,setpts=PTS-STARTPTS")
    fl.append(f"setpts=PTS/{spd}")
    vf = "[0:v]" + ",".join(fl) + "[b];"
    if opts.get("logo", True):
        vf += ("[b]split=3[m][c1][c2];"
               "[c1]crop=190:150:0:40,boxblur=14[bl1];"
               "[c2]crop=190:150:890:40,boxblur=14[bl2];"
               "[m][bl1]overlay=0:40[o1];[o1][bl2]overlay=890:40[o2];[o2]null[base]")
    else:
        vf += "[b]null[base]"
    label = "base"
    if opts.get("mask", False):
        mx, my, mw, mh = mask_region(opts)
        vf += (f";[{label}]split=2[mk0][mk1];[mk1]crop={mw}:{mh}:{mx}:{my},boxblur=20[mkb];"
               f"[mk0][mkb]overlay={mx}:{my}[masked]")
        label = "masked"
    if tpl_win:
        wx, wy, ww, wh = tpl_win
        vf += (f";[{label}]scale={ww}:{wh}:force_original_aspect_ratio=increase,crop={ww}:{wh},"
               f"pad=1080:1920:{wx}:{wy}:black[fit];[fit][2:v]overlay=0:0[framed]")
        label = "framed"
    if opts.get("caption", True):
        fx = min(1.0, max(0.0, float(opts.get("cap_x", 0.5))))
        fy = min(1.0, max(0.0, float(opts.get("cap_y", 0.88))))
        bx = f"(W-w)*{fx}"; by = f"(H-h)*{fy}"
        if opts.get("cap_anim", False):
            vf += f";[{label}][1:v]overlay={bx}:y={by}+90*((1-t/0.3)+abs(1-t/0.3))/2[v]"
        else:
            vf += f";[{label}][1:v]overlay={bx}:{by}[v]"
    else:
        vf += f";[{label}]null[v]"
    return vf

def edit_one(src, dst, cap_png, bgm, opts, tpl_path=None, start=None, seg=None, sfx=None):
    dur = probe_dur(src)
    eff = seg if seg else dur
    spd = (int(opts.get("speed", 108)) / 100.0)
    if eff > 12 and spd < 1.2: spd = 1.25
    if opts.get("evade", False): spd = round(spd * random.uniform(0.99, 1.02), 3)
    tpl_win = template_window(tpl_path) if tpl_path else None
    vf = build_vf(opts, spd, tpl_win)
    cmd = [FFMPEG, "-y"]
    if start is not None and seg:
        cmd += ["-ss", str(start), "-t", str(seg)]
    cmd += ["-i", src, "-i", cap_png]
    idx = 2
    if tpl_win:
        cmd += ["-i", tpl_path]; idx += 1
    short = False
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", bgm]; ab = f"[{idx}:a]volume=0.8[abase]"; idx += 1; short = True
    else:
        ab = f"[0:a]atempo={spd}[abase]"
    if sfx:
        cmd += ["-i", sfx]
        ab += f";[{idx}:a]volume=1.5[asfx];[abase][asfx]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"; idx += 1
    else:
        ab += ";[abase]anull[a]"
    cmd += ["-filter_complex", vf + ";" + ab, "-map", "[v]", "-map", "[a]"]
    if short: cmd += ["-shortest"]
    if start is None: cmd += ["-t", "10"]
    if opts.get("evade", False): cmd += ["-map_metadata", "-1", "-r", "30"]
    cmd += ["-c:v","libx264","-crf","20","-preset","fast","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k", dst]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0

def run_job(date, channel, bgm_name, opts, only=None):
    try:
        src_dir = os.path.join(SRC_ROOT, date)
        out_dir = os.path.join(OUT_ROOT, date); os.makedirs(out_dir, exist_ok=True)
        vids = sorted(glob.glob(os.path.join(src_dir, "*.mp4")))
        if only:
            picked = [v for v in vids if os.path.basename(v) == only]
            if picked: vids = picked
        bgm = None
        if bgm_name and not bgm_name.startswith("("):
            bgm = os.path.join(BGM_DIR, bgm_name)
            if not os.path.exists(bgm): bgm = None
        tpl_path = None
        tname = opts.get("template")
        if tname and not str(tname).startswith("("):
            p = os.path.join(BASE, "템플릿", tname)
            if os.path.exists(p): tpl_path = p
        sfx_path = resolve_sfx(opts)
        tmp = tempfile.mkdtemp(); cap = os.path.join(tmp, "cap.png")
        make_caption_png(channel or "내채널", cap,
            size=int(opts.get("cap_size", 74)),
            color=hexrgb(opts.get("cap_color", "#ffffff")),
            bold=bool(opts.get("cap_bold", False)))
        STATE.update(running=True, current=0, total=len(vids), lines=[], done=False, date=date)
        STATE["lines"].append(f"채널명: {channel} · BGM: {bgm_name} · 입력 {len(vids)}개")
        ok = 0
        for i, src in enumerate(vids, 1):
            STATE["current"] = i
            name = os.path.splitext(os.path.basename(src))[0][:34]
            good = edit_one(src, os.path.join(out_dir, f"{date}_{i:02d}.mp4"), cap, bgm, opts, tpl_path, sfx=sfx_path)
            if good: ok += 1
            STATE["lines"].append(f"[{i:02d}/{len(vids)}] {name} ... {'완료' if good else '실패'}")
        try: write_meta(out_dir, date, vids)
        except Exception: pass
        STATE["lines"].append(f"■ 끝: {ok}/{len(vids)} 성공 → 편집완료/{date}/")
    finally:
        STATE["running"] = False; STATE["done"] = True

def do_trim(data):
    try:
        date = data.get("date"); file = os.path.basename(data.get("file", ""))
        src = os.path.join(SRC_ROOT, date, file)
        if not os.path.isfile(src): return {"ok": False, "msg": "영상을 찾을 수 없음"}
        segs = data.get("segments") or []
        opts = data.get("opts", {}); channel = data.get("channel", "")
        bgm = None; bgm_name = data.get("bgm")
        if bgm_name and not str(bgm_name).startswith("("):
            bp = os.path.join(BGM_DIR, bgm_name)
            if os.path.exists(bp): bgm = bp
        tpl_path = None; tname = opts.get("template")
        if tname and not str(tname).startswith("("):
            tp = os.path.join(BASE, "템플릿", tname)
            if os.path.exists(tp): tpl_path = tp
        sfx_path = resolve_sfx(opts)
        out_dir = os.path.join(OUT_ROOT, date, "개별"); os.makedirs(out_dir, exist_ok=True)
        tmp = tempfile.mkdtemp(); cap = os.path.join(tmp, "cap.png")
        make_caption_png(channel or "내채널", cap, size=int(opts.get("cap_size", 74)),
            color=hexrgb(opts.get("cap_color", "#ffffff")), bold=bool(opts.get("cap_bold", False)), desc=opts.get("desc", ""))
        parts = []
        for i, s in enumerate(segs):
            st = float(s.get("start", 0)); en = float(s.get("end", 0))
            if en - st < 0.2: continue
            seg_text = (s.get("text") or "").strip()
            use_cap = cap
            if seg_text:
                use_cap = os.path.join(tmp, f"cap_{i:02d}.png")
                make_caption_png(seg_text, use_cap, size=int(opts.get("cap_size", 74)),
                    color=hexrgb(opts.get("cap_color", "#ffffff")), bold=bool(opts.get("cap_bold", False)), desc=opts.get("desc", ""))
            pp = os.path.join(tmp, f"part_{i:02d}.mp4")
            if edit_one(src, pp, use_cap, bgm, opts, tpl_path, start=st, seg=en-st, sfx=(sfx_path if i == 0 else None)):
                parts.append(pp)
        if not parts: return {"ok": False, "msg": "유효한 구간이 없음"}
        base = os.path.splitext(file)[0][:28]
        dst = os.path.join(out_dir, f"{base}_편집.mp4")
        if len(parts) == 1:
            import shutil; shutil.move(parts[0], dst)
        else:
            lst = os.path.join(tmp, "list.txt")
            with open(lst, "w", encoding="utf-8") as f:
                f.write("\n".join(f"file '{p}'" for p in parts))
            cc = [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", dst]
            if subprocess.run(cc, capture_output=True, text=True).returncode != 0:
                cc = [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", lst,
                      "-c:v", "libx264", "-crf", "20", "-preset", "fast", "-c:a", "aac", dst]
                subprocess.run(cc, capture_output=True, text=True)
        return {"ok": True, "out": os.path.basename(dst), "parts": len(parts)}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def do_preview(data):
    try:
        date = data.get("date"); opts = data.get("opts", {}); channel = data.get("channel", "")
        file = data.get("file")
        if file:
            src = os.path.join(SRC_ROOT, date, os.path.basename(file))
        else:
            vids = sorted(glob.glob(os.path.join(SRC_ROOT, date, "*.mp4")))
            src = vids[0] if vids else None
        if not src or not os.path.isfile(src): return None
        tpl_path = None; tname = opts.get("template")
        if tname and not str(tname).startswith("("):
            tp = os.path.join(BASE, "템플릿", tname)
            if os.path.exists(tp): tpl_path = tp
        tpl_win = template_window(tpl_path) if tpl_path else None
        tmp = tempfile.mkdtemp(); cap = os.path.join(tmp, "cap.png")
        make_caption_png(channel or "내채널", cap, size=int(opts.get("cap_size", 74)),
            color=hexrgb(opts.get("cap_color", "#ffffff")), bold=bool(opts.get("cap_bold", False)), desc=opts.get("desc", ""))
        spd = max(1.0, int(opts.get("speed", 108)) / 100.0)
        vf = build_vf(opts, spd, tpl_win)
        out = os.path.join(tmp, "preview.jpg")
        cmd = [FFMPEG, "-y", "-ss", "1", "-i", src, "-i", cap]
        if tpl_win: cmd += ["-i", tpl_path]
        cmd += ["-filter_complex", vf, "-map", "[v]", "-frames:v", "1", out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return out if (r.returncode == 0 and os.path.exists(out)) else None
    except Exception:
        return None

# ════════════════ 💀 시체영상 도굴 모듈 ════════════════
DIGG_DB = os.path.join(RUN_DIR, "shorts.db")
DIGG_STATE = {"running": False, "msg": "대기", "done": 0, "total": 0}
DIGG_SEEDS = [
    ("Timberteamhdpm","농기계"),("Village_gear","농기계"),("wisdompouchannel","지식"),
    ("WorkerVision","농기계"),("Toolholder","공구"),("TechOnlineShow","기계"),
    ("Farmcrafts-b3t","농기계"),("tomobox7763","공구"),("TUAHALAMShorts","농기계"),
    ("HangLyDIY","DIY"),("Cleversolution-i7o","DIY"),("speedfixmechanics","기계"),
    ("BrilliantVictorIndustries","기계"),("MasterMechanism-m5s","기계"),("craftspeople","공구"),
]
DIGG_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels(handle TEXT PRIMARY KEY, category TEXT, last_crawled TEXT);
CREATE TABLE IF NOT EXISTS videos(youtube_id TEXT PRIMARY KEY, handle TEXT, category TEXT, title TEXT, duration INTEGER,
  current_views INTEGER, last_views INTEGER, delta INTEGER, upload_date TEXT, age_days INTEGER,
  like_count INTEGER, comment_count INTEGER, enriched INTEGER DEFAULT 0, first_seen TEXT, last_checked TEXT);
CREATE TABLE IF NOT EXISTS snapshots(youtube_id TEXT, ts TEXT, views INTEGER);
"""

def find_ytdlp():
    names = ["yt-dlp.exe", "yt-dlp"] if sys.platform == "win32" else ["yt-dlp"]
    for d in [BUNDLE, RUN_DIR, os.path.join(RUN_DIR, "_bin_win")]:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p): return p
    return "yt-dlp"
YTDLP = find_ytdlp()

def _digg_con():
    con = sqlite3.connect(DIGG_DB); con.executescript(DIGG_SCHEMA); return con

def _ytrun(args, timeout=180):
    try: return subprocess.run([YTDLP]+args, capture_output=True, text=True, timeout=timeout).stdout
    except Exception: return ""

def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

def digg_catalog(handle, limit=0):
    args = ["--flat-playlist","--dump-json","--no-warnings"]
    if limit: args += ["--playlist-end", str(limit)]
    args += [f"https://www.youtube.com/@{handle}/shorts"]
    rows = []
    for line in _ytrun(args).splitlines():
        try:
            d = json.loads(line)
            if d.get("id") and d.get("view_count") is not None:
                rows.append((d["id"], d.get("title",""), int(d["view_count"]), d.get("duration")))
        except Exception: pass
    return rows

def digg_enrich_one(vid):
    out = _ytrun(["--dump-json","--no-warnings","--skip-download", f"https://www.youtube.com/shorts/{vid}"], timeout=60)
    try:
        d = json.loads(out); ud = d.get("upload_date"); age = None
        if ud:
            try: age = (datetime.date.today() - datetime.date(int(ud[:4]),int(ud[4:6]),int(ud[6:8]))).days
            except Exception: pass
        return ud, age, d.get("like_count"), d.get("comment_count")
    except Exception:
        return None, None, None, None

def digg_crawl(limit=0, enrich_cap=80, min_views=1000000, delay=3):
    if DIGG_STATE["running"]: return
    DIGG_STATE.update(running=True, msg="수집 시작", done=0, total=len(DIGG_SEEDS))
    try:
        con = _digg_con(); t = _utcnow()
        for i,(h,c) in enumerate(DIGG_SEEDS, 1):
            DIGG_STATE.update(msg=f"@{h} 카탈로그 수집 중", done=i, total=len(DIGG_SEEDS))
            con.execute("INSERT INTO channels(handle,category,last_crawled) VALUES(?,?,?) ON CONFLICT(handle) DO UPDATE SET last_crawled=?", (h,c,t,t))
            for vid,title,views,dur in digg_catalog(h, limit):
                row = con.execute("SELECT current_views FROM videos WHERE youtube_id=?", (vid,)).fetchone()
                if row is None:
                    con.execute("INSERT INTO videos(youtube_id,handle,category,title,duration,current_views,last_views,delta,first_seen,last_checked) VALUES(?,?,?,?,?,?,?,?,?,?)", (vid,h,c,title,dur,views,None,0,t,t))
                else:
                    con.execute("UPDATE videos SET last_views=current_views,current_views=?,delta=?,title=?,last_checked=? WHERE youtube_id=?", (views, views-row[0], title, t, vid))
                con.execute("INSERT INTO snapshots(youtube_id,ts,views) VALUES(?,?,?)", (vid, t, views))
            con.commit(); time.sleep(delay)
        cands = con.execute("SELECT youtube_id FROM videos WHERE current_views>=? AND enriched=0 ORDER BY current_views DESC LIMIT ?", (min_views, enrich_cap)).fetchall()
        DIGG_STATE.update(msg="옛영상 날짜 보강", total=len(cands), done=0)
        for i,(vid,) in enumerate(cands, 1):
            ud,age,lk,cm = digg_enrich_one(vid)
            con.execute("UPDATE videos SET upload_date=?,age_days=?,like_count=?,comment_count=?,enriched=1 WHERE youtube_id=?", (ud,age,lk,cm,vid))
            DIGG_STATE.update(done=i)
            if i % 10 == 0: con.commit()
            time.sleep(max(1.5, delay-1))
        con.commit(); con.close()
        DIGG_STATE.update(msg="완료 ✓")
    except Exception as e:
        DIGG_STATE.update(msg=f"오류: {e}")
    finally:
        DIGG_STATE["running"] = False

def digg_data(category="", min_views=1000000, age=120):
    con = _digg_con(); con.row_factory = sqlite3.Row
    cw = " AND category=? " if category else " "; ca = (category,) if category else ()
    def rows(sql, a=()):
        try: return [dict(r) for r in con.execute(sql, a).fetchall()]
        except Exception: return []
    stats = {
        "total": (rows("SELECT COUNT(*) c FROM videos") or [{"c":0}])[0]["c"],
        "channels": (rows("SELECT COUNT(*) c FROM channels") or [{"c":0}])[0]["c"],
        "enriched": (rows("SELECT COUNT(*) c FROM videos WHERE enriched=1") or [{"c":0}])[0]["c"],
        "cats": [r["category"] for r in rows("SELECT DISTINCT category FROM channels WHERE category IS NOT NULL ORDER BY category")],
    }
    digg = rows(f"SELECT youtube_id,handle,title,current_views,last_views,delta,age_days,duration FROM videos WHERE current_views>=? AND age_days>=? {cw} ORDER BY (CASE WHEN last_views IS NOT NULL AND CAST(delta AS REAL)/current_views<0.005 THEN 0 ELSE 1 END), current_views DESC LIMIT 30", (min_views, age)+ca)
    surge = rows(f"SELECT youtube_id,handle,title,current_views,last_views,delta,age_days,duration FROM videos WHERE last_views IS NOT NULL {cw} ORDER BY delta DESC LIMIT 12", ca)
    top = rows(f"SELECT youtube_id,handle,title,current_views,last_views,delta,age_days,duration FROM videos WHERE 1=1 {cw} ORDER BY current_views DESC LIMIT 24", ca)
    con.close()
    return {"stats": stats, "digg": digg, "surge": surge, "top": top, "state": DIGG_STATE}

def digg_grab(url):
    if not url: return {"ok": False, "msg": "URL 없음"}
    m = re.search(r"(?:shorts/|watch\?v=|v=|youtu\.be/|/)([A-Za-z0-9_-]{11})(?:[?&/]|$)", url)
    vid_id = m.group(1) if m else None
    day = datetime.date.today().strftime("%y%m%d")
    folder = os.path.join(SRC_ROOT, day); os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, "%(id)s.%(ext)s")
    try:
        fmt = "bestvideo[height<=1080][vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo[height<=1080][vcodec^=avc1]+bestaudio/best[height<=1080][vcodec^=avc1]/bestvideo[height<=1080]+bestaudio/best"
        subprocess.run([YTDLP,"-f",fmt,"--merge-output-format","mp4","-o",out,"--no-warnings",url], timeout=300)
        fname = f"{vid_id}.mp4" if vid_id and os.path.exists(os.path.join(folder, f"{vid_id}.mp4")) else None
        if not fname:
            mp4s = sorted(glob.glob(os.path.join(folder, "*.mp4")), key=os.path.getmtime)
            fname = os.path.basename(mp4s[-1]) if mp4s else None
        if not fname: return {"ok": False, "msg": "다운로드 파일을 찾을 수 없음"}
        return {"ok": True, "date": day, "file": fname}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

# ── 설정(BYOK 키) ──
SETTINGS_FILE = os.path.join(RUN_DIR, "settings.json")
def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception: return {}
def save_settings(d):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False, indent=2)
        return True
    except Exception: return False

def _llm_call(prompt):
    import urllib.request
    s = load_settings(); prov = s.get("llm_provider", "gemini")
    try:
        if prov == "claude":
            key = (s.get("claude_key") or "").strip()
            if not key: return None, "Claude API 키가 설정되지 않음 (⚙ 설정)"
            body = json.dumps({"model": s.get("claude_model","claude-haiku-4-5-20251001"), "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
            req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=45).read())
            return r["content"][0]["text"], None
        else:
            key = (s.get("gemini_key") or "").strip()
            if not key: return None, "Gemini API 키가 설정되지 않음 (⚙ 설정)"
            model = s.get("gemini_model", "gemini-2.0-flash")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=45).read())
            return r["candidates"][0]["content"]["parts"][0]["text"], None
    except Exception as e:
        return None, f"{prov} 호출 오류: {e}"

def gen_meta(title):
    prompt = ("당신은 한국어 유튜브 쇼츠 메타데이터 전문가입니다. 아래 해외 영상 제목을 보고 "
        "한국 시청자 대상 쇼츠 메타데이터를 만드세요.\n원본 제목: " + (title or "(제목 없음)") +
        "\n규칙: title은 호기심 자극 28자 이내, desc는 2~3문장, tags는 8~12개(한글+영문 혼합, # 포함, 관련 키워드).\n"
        '반드시 아래 JSON 형식으로만 출력: {"title":"...","desc":"...","tags":["#...","#..."]}')
    txt, err = _llm_call(prompt)
    if err: return {"ok": False, "msg": err}
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m: return {"ok": False, "msg": "LLM 응답 파싱 실패", "raw": (txt or "")[:200]}
    try:
        d = json.loads(m.group(0))
        return {"ok": True, "title": d.get("title", ""), "desc": d.get("desc", ""), "tags": d.get("tags", [])}
    except Exception as e:
        return {"ok": False, "msg": f"JSON 파싱 실패: {e}", "raw": (txt or "")[:200]}

def digg_oneclick(url, title=""):
    g = digg_grab(url)
    if not g.get("ok"): return g
    if STATE.get("running"):
        return {"ok": False, "msg": "편집 작업이 이미 진행 중입니다", "date": g["date"]}
    threading.Thread(target=run_job, args=(g["date"], channel_name(), "(원본 소리 사용)", {"evade": True}), kwargs={"only": g["file"]}, daemon=True).start()
    res = {"ok": True, "date": g["date"], "file": g["file"]}
    if (load_settings().get("gemini_key") or load_settings().get("claude_key")):
        meta = gen_meta(title)
        if meta.get("ok"): res["meta"] = meta
    return res

DIGG_HTML = r'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>💀 시체영상 도굴</title>
<style>
  :root{ --blue:#0071e3; --ink:#1d1d1f; --sub:#6e6e73; --bg:#f5f5f7; --dead:#d2691e; --good:#1a9e4b; }
  *{ box-sizing:border-box; margin:0; padding:0; }
  body{ font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif; background:var(--bg); color:var(--ink); padding:28px 22px; }
  .wrap{ max-width:1100px; margin:0 auto; }
  .top{ display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:16px; }
  h1{ font-size:23px; font-weight:700; letter-spacing:-.5px; }
  h1 .g{ color:var(--sub); font-weight:600; font-size:15px; }
  .tabs{ display:inline-flex; background:#e8e8ed; border-radius:13px; padding:4px; gap:3px; }
  .tab{ padding:9px 20px; border-radius:10px; font-size:14px; font-weight:600; color:#5f5f66; text-decoration:none; }
  .tab.active{ background:#fff; color:var(--ink); box-shadow:0 1px 4px rgba(0,0,0,.14); }
  .bar{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin:6px 0 16px; }
  .stat{ font-size:13px; color:var(--sub); }
  .btn{ background:var(--blue); color:#fff; border:none; padding:9px 16px; border-radius:11px; font-size:13.5px; font-weight:600; cursor:pointer; }
  .btn.sm{ padding:6px 11px; font-size:12px; border-radius:9px; }
  .btn.ghost{ background:#fff; color:var(--ink); box-shadow:0 1px 3px rgba(0,0,0,.1); }
  .chips{ display:flex; gap:7px; flex-wrap:wrap; margin-bottom:8px; }
  .chip{ padding:5px 12px; border-radius:999px; background:#fff; color:var(--sub); font-size:13px; cursor:pointer; box-shadow:0 1px 3px rgba(0,0,0,.06); }
  .chip.on{ background:var(--blue); color:#fff; font-weight:700; }
  h2{ font-size:16px; margin:24px 0 10px; } h2.dig{ color:var(--dead); } .hint{ font-size:12px; color:var(--sub); font-weight:400; }
  .grid{ display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:13px; }
  .card{ background:#fff; border-radius:14px; overflow:hidden; box-shadow:0 2px 10px rgba(0,0,0,.05); position:relative; }
  .card img{ width:100%; aspect-ratio:16/9; object-fit:cover; display:block; background:#ddd; }
  .rank{ position:absolute; top:7px; left:7px; background:#000a; color:#fff; font-weight:800; font-size:11px; padding:2px 7px; border-radius:7px; }
  .m{ padding:9px 11px; } .t{ font-size:12.5px; line-height:1.35; height:34px; overflow:hidden; }
  .t a{ color:var(--ink); text-decoration:none; }
  .s{ font-size:11.5px; color:var(--sub); margin-top:5px; display:flex; gap:5px; flex-wrap:wrap; align-items:center; }
  .ch{ color:var(--blue); } .dead{ color:var(--dead); font-weight:700; } .good{ color:var(--good); font-weight:700; }
  .act{ display:flex; gap:5px; margin-top:8px; } .empty{ color:var(--sub); font-size:13px; }
  #prog{ font-size:12.5px; color:var(--blue); }
</style></head><body><div class="wrap">
<div class="top"><h1>💀 시체영상 도굴 <span class="g">· 농기계/지식 (월천식)</span></h1>
  <div class="tabs"><a class="tab" href="/">🎬 대량 편집</a><a class="tab" href="/single">✂ 개별 편집</a><a class="tab active" href="/digg">💀 도굴</a><a class="tab" href="/settings">⚙ 설정</a></div>
</div>
<div class="bar">
  <button class="btn" id="crawl">📡 수집 갱신</button>
  <span id="prog"></span>
  <span class="stat" id="stats"></span>
</div>
<div class="chips" id="chips"></div>
<h2 class="dig">💀 도굴 후보 <span class="hint">— 100만+ 조회 · 120일+ 옛영상 · 성장 멈춘 것 우선 (= 월천 핵심)</span></h2>
<div class="grid" id="digg"></div>
<h2 style="color:var(--good)">🔥 급상승 <span class="hint">(24h 증가량 · 매일 수집해야 잡힘)</span></h2><div class="grid" id="surge"></div>
<h2 style="color:var(--blue)">📈 조회수 상위</h2><div class="grid" id="top"></div>
</div>
<div id="metaPanel" style="display:none;position:fixed;left:0;right:0;bottom:0;background:#fff;box-shadow:0 -4px 20px rgba(0,0,0,.18);padding:14px 18px;z-index:50">
  <div style="max-width:760px;margin:0 auto">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <b id="metaStatus">📋 생성된 메타데이터</b>
      <span><button class="btn sm" id="metaCopy">📋 전체 복사</button> <button class="btn ghost sm" id="metaClose">닫기</button></span>
    </div>
    <textarea id="metaText" style="width:100%;height:140px;border:1px solid #d2d2d7;border-radius:10px;padding:10px;font-size:13px;font-family:inherit"></textarea>
  </div>
</div>
<script>
document.getElementById('metaClose').onclick=()=>document.getElementById('metaPanel').style.display='none';
document.getElementById('metaCopy').onclick=()=>{ const t=document.getElementById('metaText'); t.select(); navigator.clipboard.writeText(t.value); const b=document.getElementById('metaCopy'); b.textContent='✓ 복사됨'; setTimeout(()=>b.textContent='📋 전체 복사',1500); };
let CAT="";
const nf=n=>Number(n).toLocaleString();
function ageL(d){ if(!d) return ""; if(d>=365) return Math.floor(d/365)+"년전"; if(d>=30) return Math.floor(d/30)+"개월전"; return d+"일전"; }
function card(v,rank){
  const id=v.youtube_id, yt="https://www.youtube.com/shorts/"+id, th="https://i.ytimg.com/vi/"+id+"/mqdefault.jpg";
  let flat="";
  if(v.last_views!=null && v.current_views){ const r=v.delta/v.current_views; flat = r<0.005 ? '<span class="dead">💀누움</span>' : (v.delta>0?'<span class="good">📈+'+nf(v.delta)+'</span>':''); }
  const age=v.age_days?('🗓'+ageL(v.age_days)):'';
  return `<div class="card"><span class="rank">${rank}</span>
   <a href="${yt}" target="_blank"><img loading="lazy" src="${th}"></a>
   <div class="m"><div class="t"><a href="${yt}" target="_blank">${(v.title||'').slice(0,70)}</a></div>
   <div class="s"><span class="ch">@${v.handle}</span> · 👁${nf(v.current_views)} ${age} ${flat}</div>
   <div class="act"><a class="btn ghost sm" href="${yt}" target="_blank">유튜브</a>
   <button class="btn ghost sm meta" data-title="${(v.title||'').replace(/"/g,'&quot;').slice(0,140)}">📋 제목·태그</button>
   <button class="btn ghost sm make" data-url="${yt}">⬇ 다운만</button>
   <button class="btn sm one" data-url="${yt}" data-title="${(v.title||'').replace(/"/g,'&quot;').slice(0,140)}">⚡ 원클릭</button></div></div></div>`;
}
function render(id,arr){ document.getElementById(id).innerHTML = arr.length ? arr.map((v,i)=>card(v,i+1)).join("") : '<p class="empty">데이터가 없어요. "📡 수집 갱신"을 누르세요.</p>'; bind(); }
function fmtMeta(m){ return `${m.title}\n\n${m.desc}\n\n${(m.tags||[]).join(' ')}`; }
function showMeta(text,status){ document.getElementById('metaText').value=text; document.getElementById('metaStatus').textContent=status||'📋 생성된 메타데이터'; document.getElementById('metaPanel').style.display='block'; }
function bind(){
  document.querySelectorAll('.make').forEach(b=>b.onclick=async()=>{
    b.textContent='⬇ 가져오는 중…'; b.disabled=true;
    const r=await fetch('/api/digg_grab',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:b.dataset.url})}).then(r=>r.json());
    b.textContent = r.ok ? '✓ '+r.date+' 폴더로' : '✗ 실패'; if(r.ok) b.style.background='#1a9e4b';
  });
  document.querySelectorAll('.meta').forEach(b=>b.onclick=async()=>{
    const o=b.textContent; b.textContent='🤖 생성 중…'; b.disabled=true;
    const r=await fetch('/api/gen_meta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:b.dataset.title})}).then(r=>r.json());
    b.disabled=false; b.textContent=o;
    if(r.ok) showMeta(fmtMeta(r),'📋 제목·태그 (복사해서 업로드)');
    else showMeta((r.msg||'실패')+(r.raw?'\n\n'+r.raw:''),'⚠ 생성 실패 — ⚙ 설정에서 API 키 확인');
  });
  document.querySelectorAll('.one').forEach(b=>b.onclick=async()=>{
    b.textContent='⬇ 다운로드 중…'; b.disabled=true;
    const r=await fetch('/api/digg_oneclick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:b.dataset.url,title:b.dataset.title})}).then(r=>r.json());
    if(!r.ok){ b.textContent='✗ '+(r.msg||'실패'); return; }
    if(r.meta) showMeta(fmtMeta(r.meta),'📋 제목·태그 (편집 진행 중 · 복사 가능)');
    b.textContent='✂ 편집 시작…';
    let started=false;
    const poll=async()=>{
      const s=await fetch('/api/progress').then(r=>r.json());
      if(s.running){ started=true; b.textContent=`✂ 편집 중… ${s.current}/${s.total}`; setTimeout(poll,1500); }
      else if(started && s.done){ b.textContent='✓ 완성 → 편집완료/'+r.date; b.style.background='#1a9e4b'; }
      else setTimeout(poll,1500);
    };
    setTimeout(poll,1500);
  });
}
async function load(){
  const r=await fetch('/api/digg?cat='+encodeURIComponent(CAT)).then(r=>r.json());
  const s=r.stats;
  document.getElementById('stats').textContent=`채널 ${s.channels} · 영상 ${nf(s.total)} · 날짜보강 ${s.enriched}`;
  document.getElementById('chips').innerHTML=['<span class="chip '+(CAT===''?'on':'')+'" data-c="">전체</span>'].concat((s.cats||[]).map(c=>'<span class="chip '+(CAT===c?'on':'')+'" data-c="'+c+'">'+c+'</span>')).join('');
  document.querySelectorAll('.chip').forEach(ch=>ch.onclick=()=>{ CAT=ch.dataset.c; load(); });
  render('digg',r.digg); render('surge',r.surge); render('top',r.top);
  const st=r.state; document.getElementById('prog').textContent = st.running ? `⏳ ${st.msg} (${st.done}/${st.total})` : (st.msg==='완료 ✓'?'✓ 수집 완료':'');
  if(st.running) setTimeout(load,2500);
}
document.getElementById('crawl').onclick=async()=>{
  await fetch('/api/digg_crawl',{method:'POST'}); document.getElementById('prog').textContent='⏳ 수집 시작…'; setTimeout(load,1500);
};
load();
</script></body></html>'''
SETTINGS_HTML = r'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>⚙ 설정</title><style>
  :root{ --blue:#0071e3; --ink:#1d1d1f; --sub:#6e6e73; --bg:#f5f5f7; }
  *{ box-sizing:border-box; margin:0; padding:0; }
  body{ font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif; background:var(--bg); color:var(--ink); padding:28px 22px; }
  .wrap{ max-width:640px; margin:0 auto; }
  .top{ display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:18px; }
  h1{ font-size:22px; font-weight:700; letter-spacing:-.5px; }
  .tabs{ display:inline-flex; background:#e8e8ed; border-radius:13px; padding:4px; gap:3px; }
  .tab{ padding:9px 18px; border-radius:10px; font-size:14px; font-weight:600; color:#5f5f66; text-decoration:none; }
  .tab.active{ background:#fff; color:var(--ink); box-shadow:0 1px 4px rgba(0,0,0,.14); }
  .card{ background:#fff; border-radius:16px; padding:22px; box-shadow:0 2px 12px rgba(0,0,0,.05); margin-bottom:16px; }
  h2{ font-size:16px; margin-bottom:14px; }
  label{ display:block; font-size:13px; color:var(--sub); margin:14px 0 6px; font-weight:600; }
  input[type=text],input[type=password],select{ width:100%; padding:11px 13px; border:1px solid #d2d2d7; border-radius:11px; font-size:14px; background:#fff; }
  .prov{ display:flex; gap:10px; margin-top:6px; }
  .prov label{ flex:1; margin:0; padding:12px; border:2px solid #e3e3e8; border-radius:12px; text-align:center; cursor:pointer; font-weight:700; color:var(--ink); }
  .prov input{ display:none; }
  .prov input:checked+span{ color:var(--blue); }
  .prov label.on{ border-color:var(--blue); background:#f0f7ff; }
  .hint{ font-size:12px; color:var(--sub); margin-top:5px; line-height:1.5; }
  .hint a{ color:var(--blue); }
  .saved{ font-size:12px; color:#1a9e4b; margin-left:8px; }
  .btn{ background:var(--blue); color:#fff; border:none; padding:12px 22px; border-radius:12px; font-size:15px; font-weight:700; cursor:pointer; margin-top:20px; }
</style></head><body><div class="wrap">
<div class="top"><h1>⚙ 설정</h1>
  <div class="tabs"><a class="tab" href="/">🎬 대량 편집</a><a class="tab" href="/single">✂ 개별 편집</a><a class="tab" href="/digg">💀 도굴</a><a class="tab active" href="/settings">⚙ 설정</a></div>
</div>
<div class="card">
  <h2>🤖 제목·해시태그 생성 LLM (BYOK)</h2>
  <label>사용할 AI</label>
  <div class="prov" id="prov">
    <label data-p="gemini"><input type="radio" name="prov" value="gemini"><span>Gemini (무료)</span></label>
    <label data-p="claude"><input type="radio" name="prov" value="claude"><span>Claude</span></label>
  </div>
  <label>Gemini API 키 <span class="saved" id="g_saved"></span></label>
  <input type="password" id="gemini_key" placeholder="비워두면 기존 키 유지">
  <div class="hint">무료 키 발급: <a href="https://aistudio.google.com/apikey" target="_blank">aistudio.google.com/apikey</a> (비용 0, 분당 제한 있음)</div>
  <label>Claude API 키 <span class="saved" id="c_saved"></span></label>
  <input type="password" id="claude_key" placeholder="비워두면 기존 키 유지">
  <div class="hint">발급: <a href="https://console.anthropic.com/" target="_blank">console.anthropic.com</a> (유료)</div>
  <button class="btn" id="save">저장</button> <span class="saved" id="msg"></span>
</div>
</div>
<script>
async function load(){
  const s=await fetch('/api/settings').then(r=>r.json());
  document.querySelector(`input[value="${s.llm_provider}"]`).checked=true;
  paint(); document.getElementById('g_saved').textContent=s.has_gemini?'✓ 저장됨':'';
  document.getElementById('c_saved').textContent=s.has_claude?'✓ 저장됨':'';
}
function paint(){ document.querySelectorAll('#prov label').forEach(l=>l.classList.toggle('on', l.querySelector('input').checked)); }
document.getElementById('prov').onclick=()=>setTimeout(paint,0);
document.getElementById('save').onclick=async()=>{
  const body={ llm_provider:document.querySelector('input[name=prov]:checked').value,
    gemini_key:document.getElementById('gemini_key').value, claude_key:document.getElementById('claude_key').value };
  const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
  document.getElementById('msg').textContent=r.ok?'✓ 저장 완료':'✗ 실패';
  document.getElementById('gemini_key').value=''; document.getElementById('claude_key').value=''; setTimeout(load,300);
};
load();
</script></body></html>'''
# ════════════════ 도굴 모듈 끝 ════════════════

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/" or p == "/index.html":
            html = DASHBOARD_HTML
            return self._send(200, html, "text/html; charset=utf-8")
        if p == "/api/state":
            dfs = date_folders(); d = dfs[0] if dfs else ""
            return self._send(200, json.dumps({
                "version": VERSION, "dates": dfs, "latest": d, "count": count_videos(d),
                "channel": channel_name(), "bgms": bgm_list(), "templates": template_list(), "sfx": sfx_list()}))
        if p == "/api/progress":
            return self._send(200, json.dumps(STATE))
        if p == "/api/count":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._send(200, json.dumps({"count": count_videos((q.get("date") or [""])[0])}))
        if p == "/api/open":
            d = STATE.get("date") or (date_folders()[0] if date_folders() else "")
            folder = os.path.join(OUT_ROOT, d)
            try:
                if sys.platform == "win32": os.startfile(folder)
                elif sys.platform == "darwin": subprocess.Popen(["open", folder])
                else: subprocess.Popen(["xdg-open", folder])
            except Exception: pass
            return self._send(200, json.dumps({"ok": True}))
        if p == "/api/shutdown":
            self._send(200, json.dumps({"ok": True}))
            threading.Timer(0.4, lambda: os._exit(0)).start()
            return
        if p == "/single":
            html = SINGLE_HTML
            return self._send(200, html, "text/html; charset=utf-8")
        if p == "/api/files":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query); date = (q.get("date") or [""])[0]
            files = [os.path.basename(x) for x in sorted(glob.glob(os.path.join(SRC_ROOT, date, "*.mp4")))]
            return self._send(200, json.dumps({"files": files, "dates": date_folders()}))
        if p == "/video":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self.serve_video(os.path.join(SRC_ROOT, (q.get("date") or [""])[0], os.path.basename((q.get("file") or [""])[0])))
        if p == "/digg":
            return self._send(200, DIGG_HTML, "text/html; charset=utf-8")
        if p == "/api/digg":
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            return self._send(200, json.dumps(digg_data((q.get("cat") or [""])[0])))
        if p == "/settings":
            return self._send(200, SETTINGS_HTML, "text/html; charset=utf-8")
        if p == "/api/settings":
            s = load_settings()
            return self._send(200, json.dumps({"llm_provider": s.get("llm_provider", "gemini"),
                "has_gemini": bool(s.get("gemini_key")), "has_claude": bool(s.get("claude_key")),
                "gemini_model": s.get("gemini_model", "gemini-2.0-flash"),
                "claude_model": s.get("claude_model", "claude-haiku-4-5-20251001")}))
        return self._send(404, "{}")
    def serve_video(self, path):
        if not (os.path.isfile(path) and path.lower().endswith(".mp4")):
            return self._send(404, "{}")
        fsize = os.path.getsize(path); rng = self.headers.get("Range")
        start, end, status = 0, fsize-1, 200
        if rng and rng.startswith("bytes="):
            status = 206; a, _, b = rng[6:].partition("-")
            start = int(a) if a else 0; end = int(b) if b else fsize-1
        end = min(end, fsize-1); length = end-start+1
        self.send_response(status); self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        if status == 206: self.send_header("Content-Range", f"bytes {start}-{end}/{fsize}")
        self.send_header("Content-Length", str(length)); self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start); rem = length
                while rem > 0:
                    chunk = f.read(min(262144, rem))
                    if not chunk: break
                    self.wfile.write(chunk); rem -= len(chunk)
        except Exception: pass
    def do_POST(self):
        if self.path == "/api/run":
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            if STATE["running"]:
                return self._send(200, json.dumps({"ok": False, "msg": "이미 작업 중"}))
            t = threading.Thread(target=run_job, args=(
                data.get("date"), data.get("channel"), data.get("bgm"), data.get("opts", {})), daemon=True)
            t.start()
            return self._send(200, json.dumps({"ok": True}))
        if self.path == "/api/trim":
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            return self._send(200, json.dumps(do_trim(data)))
        if self.path == "/api/preview":
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            out = do_preview(data)
            if out:
                with open(out, "rb") as f: img = f.read()
                return self._send(200, img, "image/jpeg")
            return self._send(200, b"", "image/jpeg")
        if self.path == "/api/digg_crawl":
            if not DIGG_STATE["running"]:
                threading.Thread(target=digg_crawl, daemon=True).start()
            return self._send(200, json.dumps({"ok": True}))
        if self.path == "/api/digg_grab":
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            return self._send(200, json.dumps(digg_grab(data.get("url", ""))))
        if self.path == "/api/digg_oneclick":
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            return self._send(200, json.dumps(digg_oneclick(data.get("url", ""), data.get("title", ""))))
        if self.path == "/api/gen_meta":
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            return self._send(200, json.dumps(gen_meta(data.get("title", ""))))
        if self.path == "/api/settings":
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            cur = load_settings()
            cur["llm_provider"] = data.get("llm_provider", cur.get("llm_provider", "gemini"))
            for k in ("gemini_key", "claude_key", "gemini_model", "claude_model"):
                v = (data.get(k) or "").strip()
                if v: cur[k] = v
            return self._send(200, json.dumps({"ok": save_settings(cur)}))
        return self._send(404, "{}")

def main():
    ensure_dirs()
    port = 8799
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}/"
    print(f"쇼츠 자동편집 대시보드 실행 중 → {url}")
    try: webbrowser.open(url)
    except Exception: pass
    srv.serve_forever()

if __name__ == "__main__":
    main()
