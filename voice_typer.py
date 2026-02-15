import keyboard
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
import pyperclip
import threading
import queue
import time
import sys
import os
import re
import json
import collections
import winsound
import ctypes
import ctypes.wintypes as wintypes
import subprocess
from string import Template

import webview
from PIL import Image, ImageDraw

from config import (
    HOTKEY, MODEL_SIZE, DEVICE, COMPUTE_TYPE, LANGUAGE,
    SILENCE_PAUSE, SILENCE_MULTIPLIER, SAMPLE_RATE, INPUT_DEVICE,
    VOICE_COMMANDS, AUTO_CAPITALIZE, ENABLE_TRAY_ICON,
)

# DPI awareness — must be set before any window creation
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

# Get DPI scale factor so window sizes match CSS pixels
_DPI_SCALE = 1.0
try:
    _dc = ctypes.windll.user32.GetDC(0)
    _dpi = ctypes.windll.gdi32.GetDeviceCaps(_dc, 88)  # LOGPIXELSX
    ctypes.windll.user32.ReleaseDC(0, _dc)
    _DPI_SCALE = _dpi / 96.0
except Exception:
    pass

VERSION = "1.0.0"

# Special control characters used as action signals
ACTION_BACKSPACE = "\x08"
ACTION_DELETE_PHRASE = "\x7f"
ACTION_UNDO = "\x1a"
ACTION_SELECT_ALL = "\x01"

# APP_DIR = folder next to exe (settings live here).
# BUNDLE_DIR = where PyInstaller puts --add-data files (_internal/ when frozen).
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
    BUNDLE_DIR = sys._MEIPASS
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR
MODELS_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "Whisper", "models"
)
os.makedirs(MODELS_DIR, exist_ok=True)
ICON_PATH = next(
    (p for p in (os.path.join(BUNDLE_DIR, n) for n in ("icon.png", "icon.ico"))
     if os.path.exists(p)),
    os.path.join(BUNDLE_DIR, "icon.ico"),
)
SETTINGS_FILE = os.path.join(APP_DIR, ".settings.json")
STARTUP_LINK = os.path.join(
    os.environ.get("APPDATA", ""),
    r"Microsoft\Windows\Start Menu\Programs\Startup\Whisper.lnk",
)
WAVE_BARS = 16
WIN_W = int(320 * _DPI_SCALE)
WIN_W_MINI = int(100 * _DPI_SCALE)
WIN_H = int(36 * _DPI_SCALE)
WIN_H_EXPANDED = int(540 * _DPI_SCALE)
AUTO_STOP_SECONDS = 7.0
INTERIM_SECONDS = 1.5  # seconds of speech before interim transcription fires

# Win32 constants
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
LWA_ALPHA = 0x02
WM_SETICON = 0x0080
ICON_BIG = 1
ICON_SMALL = 0
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

ALPHA_IDLE = 191      # 75% opacity
ALPHA_ACTIVE = 255    # 100% opacity
ALPHA_FADE_DELAY = 2  # seconds before fading back

# Theme gray palettes (darkest → lightest); brightest g1 = #666
_THEME_COLORS = [
    ('#111111', '#1c1c1c', '#282828', '#505050'),
    ('#1a1a1a', '#252525', '#303030', '#555555'),
    ('#222222', '#2d2d2d', '#383838', '#555555'),
    ('#2a2a2a', '#353535', '#404040', '#606060'),
    ('#333333', '#3e3e3e', '#494949', '#666666'),
]
_THEME_DIM = ['#555555', '#666666', '#777777', '#888888', '#999999']

_SIZES_MB = {
    "tiny": 75, "base": 142, "small": 466,
    "medium": 1500, "large-v3": 3000, "large-v2": 3000,
}


def _screen_width():
    try:
        return ctypes.windll.user32.GetSystemMetrics(0)
    except Exception:
        return 1920


def _load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(data):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _startup_enabled():
    return os.path.exists(STARTUP_LINK)


def _set_startup(enabled):
    if enabled:
        script = (
            f'$ws=New-Object -ComObject WScript.Shell;'
            f'$s=$ws.CreateShortcut("{STARTUP_LINK}");'
            f'$s.TargetPath="{sys.executable if getattr(sys, "frozen", False) else os.path.join(APP_DIR, "voice_typer.py")}";'
            f'$s.WorkingDirectory="{APP_DIR}";'
            f'$s.WindowStyle=7;$s.Description="Whisper";$s.Save()'
        )
        subprocess.run(["powershell", "-Command", script],
                       capture_output=True, timeout=10)
    else:
        try:
            os.remove(STARTUP_LINK)
        except Exception:
            pass


def _parse_hotkey(hotkey_str):
    """Parse 'windows+j' into (modifier_flags, virtual_key) for RegisterHotKey."""
    _MOD = {
        "windows": 0x0008, "win": 0x0008,
        "ctrl": 0x0002, "control": 0x0002,
        "alt": 0x0001, "shift": 0x0004,
    }
    parts = [p.strip().lower() for p in hotkey_str.split("+")]
    mod, vk = 0, 0
    for p in parts:
        if p in _MOD:
            mod |= _MOD[p]
        elif len(p) == 1:
            vk = ord(p.upper())
    return mod, vk


HTML = Template(r"""<!DOCTYPE html>
<html><head><style>
:root{--g1:$g1;--g2:$g2;--g3:$g3;--g4:$g4}
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:var(--g1);font-family:'Segoe UI',sans-serif;
  user-select:none;-webkit-user-select:none;height:100%;overflow:hidden}
.wrap{position:relative;height:100%}
.bar{display:flex;align-items:center;background:var(--g1);height:36px;
  position:relative;z-index:200}
.mic{width:36px;height:36px;display:flex;align-items:center;justify-content:center;
  background:var(--g1);cursor:pointer;transition:background .15s;flex-shrink:0;
  -webkit-app-region:no-drag}
.mic:hover{background:var(--g2)}
.mic.on{background:#b91c1c}
.mic.on:hover{background:#dc2626}
.mic svg{pointer-events:none}
.dragzone{-webkit-app-region:drag;flex:1;display:flex;align-items:center;
  height:36px;padding:0 6px}
.status{color:var(--g4);font-size:10px;padding:0 4px 0 0;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;flex-shrink:1;min-width:60px}
.wave{display:flex;align-items:center;gap:2px;height:24px;flex-shrink:0;
  margin-left:auto}
.wb{width:3px;min-height:3px;height:3px;background:var(--g2);border-radius:1.5px;
  transition:height 80ms ease-out,background 80ms ease-out}
.btn{-webkit-app-region:no-drag;width:36px;height:36px;display:flex;align-items:center;
  justify-content:center;cursor:pointer;transition:background .12s;flex-shrink:0}
.dd:hover{background:var(--g2)}
.dd svg{opacity:.6;pointer-events:none}
.cls:hover{background:#c42b1c}
.cls svg{opacity:.7;pointer-events:none}
.cls:hover svg{opacity:1}
.overlay{display:none;position:fixed;top:36px;left:0;right:0;bottom:0;z-index:50}
.overlay.open{display:block}
.menu{display:none;position:absolute;right:0;top:36px;left:0;
  background:var(--g1);z-index:100;overflow:visible;padding:4px 0}
.menu.open{display:block}
.mi{padding:6px 12px;color:#bbb;font-size:11px;cursor:pointer;transition:background .1s;
  display:flex;align-items:center;gap:6px}
.mi:hover{background:var(--g2)}
.mi.noclick{cursor:default}
.mi.noclick:hover{background:transparent}
.mi .check{width:14px;color:#0078d4;font-weight:bold;flex-shrink:0;font-size:12px}
.sep{height:1px;background:var(--g3);margin:3px 8px}
.lbl{padding:4px 12px;color:var(--g4);font-size:9px;text-transform:uppercase;
  letter-spacing:.5px}
.csel-row{display:flex;gap:6px;width:100%;-webkit-app-region:no-drag}
.csel{position:relative;flex:1;display:flex;flex-direction:column;gap:2px}
.csel label{color:var(--g4);font-size:9px;text-transform:uppercase;letter-spacing:.3px}
.csel-btn{background:var(--g2);color:#bbb;border:1px solid var(--g3);
  padding:5px 22px 5px 8px;font-size:11px;font-family:inherit;border-radius:3px;
  cursor:pointer;position:relative;display:flex;align-items:center}
.csel-btn:hover{background:var(--g3);border-color:var(--g4)}
.csel-btn svg{position:absolute;right:6px;top:50%;transform:translateY(-50%);
  pointer-events:none}
.csel-btn svg path{fill:var(--g4)}
.csel-dd{display:none;position:absolute;top:100%;left:0;right:0;
  background:var(--g2);border:1px solid var(--g3);border-radius:4px;
  margin-top:4px;z-index:500;max-height:200px;overflow-y:auto;padding:4px 0;
  box-shadow:0 8px 24px rgba(0,0,0,0.4)}
.csel-dd.open{display:block}
.csel-opt{padding:7px 12px;color:#999;font-size:11px;cursor:pointer;
  transition:all .1s;display:flex;align-items:center;justify-content:space-between}
.csel-opt:hover{background:rgba(255,255,255,0.06);color:#eee}
.csel-opt.selected{color:#0078d4;font-weight:600}
.csel-opt.selected::after{content:'\2713';color:#0078d4;font-weight:700;font-size:12px}
.csel-dd::-webkit-scrollbar{width:5px}
.csel-dd::-webkit-scrollbar-track{background:var(--g2)}
.csel-dd::-webkit-scrollbar-thumb{background:var(--g3);border-radius:3px}
.transcript{max-height:100px;overflow-y:auto;background:var(--g1);border:1px solid var(--g3);
  padding:6px 8px;margin:3px 8px;color:#999;font-size:11px;
  user-select:text;-webkit-user-select:text;white-space:pre-wrap;word-wrap:break-word;
  line-height:1.4;-webkit-app-region:no-drag}
.transcript:empty::before{content:"Speech will appear here...";color:var(--g3);font-style:italic}
.transcript::-webkit-scrollbar{width:5px}
.transcript::-webkit-scrollbar-track{background:var(--g1)}
.transcript::-webkit-scrollbar-thumb{background:var(--g3);border-radius:3px}
.theme-row{display:flex;gap:8px;-webkit-app-region:no-drag}
.swatch{width:24px;height:24px;border:2px solid var(--g3);cursor:pointer;
  transition:border-color .15s}
.swatch:hover{border-color:#bbb}
.swatch.active{border-color:#0078d4}
.mi.restart-action{color:#e0c060;display:none}
.mi.restart-action.show{display:flex}
.mini .status{display:none}
.mini .cls{display:none}
.mini .mic{width:28px}
.mini .dragzone{padding:0 2px}
.mini .wave{margin-left:0}
.mini .wb:nth-child(n+7){display:none}
.mini .btn.dd{width:28px}
</style></head><body>
<div class="wrap">
  <div class="bar">
    <div class="mic" id="mic" onclick="toggle()">
      <svg id="micSvg" width="14" height="14" viewBox="0 0 24 24" fill="none">
        <path d="M19 10V12C19 15.866 15.866 19 12 19M5 10V12C5 15.866 8.13401 19 12 19M12 19V22M8 22H16M12 15C10.3431 15 9 13.6569 9 12V5C9 3.34315 10.3431 2 12 2C13.6569 2 15 3.34315 15 5V12C15 13.6569 13.6569 15 12 15Z" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <svg id="stopSvg" style="display:none" width="14" height="14" viewBox="0 0 32 32" fill="#fff">
        <path d="M5.92 24.096q0 .832.576 1.408t1.44.608h16.128q.832 0 1.44-.608t.576-1.408V7.936q0-.832-.576-1.44t-1.44-.576H7.936q-.832 0-1.44.576T5.92 7.936v16.16z"/>
      </svg>
    </div>
    <div class="dragzone" id="dragzone">
      <div class="status" id="st">Loading...</div>
      <div class="wave" id="wave"></div>
    </div>
    <div class="btn dd" onclick="ddToggle(event)">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
        <path d="M6 9L12 15L18 9" stroke="#888" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>
    <div class="btn cls" onclick="closeApp()">
      <svg width="10" height="10" viewBox="0 0 24 24" fill="#fff">
        <path d="M20.746 3.329a1 1 0 00-1.415 0L12.037 10.623 4.743 3.329a1 1 0 00-1.415 1.414l7.294 7.294-7.294 7.294a1 1 0 001.415 1.414l7.294-7.294 7.294 7.294a1 1 0 001.415-1.414l-7.294-7.294 7.294-7.294a1 1 0 000-1.414z"/>
      </svg>
    </div>
  </div>
  <div class="overlay" id="ov" onclick="ddClose()"></div>
  <div class="menu" id="menu">
    <div class="mi" onclick="toggleSetting(event,'auto_type')">
      <span class="check" id="chk_auto_type"></span> Auto-type
    </div>
    <div class="sep"></div>
    <div class="mi" onclick="recal()">Recalibrate</div>
    <div class="sep"></div>
    <div class="lbl">Transcript</div>
    <div class="transcript" id="transcript" onclick="event.stopPropagation()"></div>
    <div class="sep"></div>
    <div class="mi noclick" onclick="event.stopPropagation()">
      <div class="csel-row">
        <div class="csel" id="csel_model">
          <label>Model</label>
          <div class="csel-btn" onclick="cselToggle('csel_model',event)">
            <span id="csel_model_val">small (466 MB)</span>
            <svg width="8" height="5" viewBox="0 0 8 5"><path d="M0 0l4 5 4-5z" fill="#555"/></svg>
          </div>
          <div class="csel-dd" id="csel_model_dd">
            <div class="csel-opt" data-val="tiny" onclick="cselPick('model_size','tiny',this)">tiny (75 MB)</div>
            <div class="csel-opt" data-val="base" onclick="cselPick('model_size','base',this)">base (142 MB)</div>
            <div class="csel-opt" data-val="small" onclick="cselPick('model_size','small',this)">small (466 MB)</div>
            <div class="csel-opt" data-val="medium" onclick="cselPick('model_size','medium',this)">medium (1.5 GB)</div>
            <div class="csel-opt" data-val="large-v3" onclick="cselPick('model_size','large-v3',this)">large-v3 (3 GB)</div>
          </div>
        </div>
        <div class="csel" id="csel_device">
          <label>Device</label>
          <div class="csel-btn" onclick="cselToggle('csel_device',event)">
            <span id="csel_device_val">CPU — int8</span>
            <svg width="8" height="5" viewBox="0 0 8 5"><path d="M0 0l4 5 4-5z" fill="#555"/></svg>
          </div>
          <div class="csel-dd" id="csel_device_dd">
            <div class="csel-opt" data-val="cpu/int8" onclick="cselPick('device_mode','cpu/int8',this)">CPU — int8</div>
            <div class="csel-opt" data-val="cpu/float32" onclick="cselPick('device_mode','cpu/float32',this)">CPU — float32</div>
            <div class="csel-opt" data-val="cuda/float16" onclick="cselPick('device_mode','cuda/float16',this)">GPU — float16</div>
            <div class="csel-opt" data-val="cuda/int8" onclick="cselPick('device_mode','cuda/int8',this)">GPU — int8</div>
          </div>
        </div>
      </div>
    </div>
    <div class="sep"></div>
    <div class="lbl">Theme</div>
    <div class="mi noclick" onclick="event.stopPropagation()">
      <div class="theme-row" id="theme_row">
        <div class="swatch" onclick="setTheme(0)" style="background:#111"></div>
        <div class="swatch" onclick="setTheme(1)" style="background:#1a1a1a"></div>
        <div class="swatch" onclick="setTheme(2)" style="background:#222"></div>
        <div class="swatch" onclick="setTheme(3)" style="background:#2a2a2a"></div>
        <div class="swatch" onclick="setTheme(4)" style="background:#333"></div>
      </div>
    </div>
    <div class="sep"></div>
    <div class="lbl">Options</div>
    <div class="mi" onclick="toggleSetting(event,'close_to_tray')">
      <span class="check" id="chk_close_to_tray"></span> Close to tray
    </div>
    <div class="mi" onclick="toggleSetting(event,'start_with_windows')">
      <span class="check" id="chk_start_with_windows"></span> Start with Windows
    </div>
    <div class="mi" onclick="toggleSetting(event,'start_minimized')">
      <span class="check" id="chk_start_minimized"></span> Run in background
    </div>
    <div class="sep"></div>
    <div class="mi restart-action" id="restart_btn" onclick="restartApp()">Restart to apply changes</div>
    <div class="mi" onclick="quitApp()">Quit</div>
  </div>
</div>
<script>
const N=$wave_bars;
const w=document.getElementById("wave");
for(let i=0;i<N;i++){const b=document.createElement("div");b.className="wb";b.id="b"+i;w.appendChild(b)}

const THEMES=[
  {g1:'#111111',g2:'#1c1c1c',g3:'#282828',g4:'#505050'},
  {g1:'#1a1a1a',g2:'#252525',g3:'#303030',g4:'#555555'},
  {g1:'#222222',g2:'#2d2d2d',g3:'#383838',g4:'#555555'},
  {g1:'#2a2a2a',g2:'#353535',g3:'#404040',g4:'#606060'},
  {g1:'#333333',g2:'#3e3e3e',g3:'#494949',g4:'#666666'},
];
let _curTheme=-1;
function applyTheme(i){
  if(i===_curTheme)return;
  _curTheme=i;
  const t=THEMES[i];if(!t)return;
  const r=document.documentElement.style;
  r.setProperty('--g1',t.g1);r.setProperty('--g2',t.g2);
  r.setProperty('--g3',t.g3);r.setProperty('--g4',t.g4);
  document.querySelectorAll('.swatch').forEach((s,j)=>{
    if(j===i)s.classList.add('active');else s.classList.remove('active');
  });
}
function setTheme(i){_curTheme=-1;applyTheme(i);changeSetting('theme',i);}

function toggle(){pywebview.api.toggle_recording()}
function closeApp(){pywebview.api.close_app()}
function quitApp(){pywebview.api.quit_app()}
function restartApp(){pywebview.api.restart_app()}
function recal(){ddClose();pywebview.api.recalibrate()}

function toggleSetting(e,key){
  e.stopPropagation();
  pywebview.api.toggle_setting(key);
}
function changeSetting(key,val){
  pywebview.api.change_setting(key,val);
}

function cselToggle(id,e){
  e.stopPropagation();
  const dd=document.getElementById(id+'_dd');
  const isOpen=dd.classList.contains('open');
  document.querySelectorAll('.csel-dd.open').forEach(d=>d.classList.remove('open'));
  if(!isOpen)dd.classList.add('open');
}
function cselPick(key,val,el){
  changeSetting(key,val);
  const dd=el.closest('.csel-dd');
  dd.querySelectorAll('.csel-opt').forEach(o=>o.classList.remove('selected'));
  el.classList.add('selected');
  const csel=el.closest('.csel');
  const span=csel.querySelector('.csel-btn span');
  if(span)span.textContent=el.textContent;
  dd.classList.remove('open');
}
document.addEventListener('click',function(){
  document.querySelectorAll('.csel-dd.open').forEach(d=>d.classList.remove('open'));
});

async function ddToggle(e){
  e.stopPropagation();
  const m=document.getElementById("menu"),o=document.getElementById("ov");
  if(m.classList.contains("open")){ddClose()}
  else{
    await pywebview.api.expand_window();
    m.classList.add("open");o.classList.add("open");
  }
}
async function ddClose(){
  document.querySelectorAll('.csel-dd.open').forEach(d=>d.classList.remove('open'));
  const m=document.getElementById("menu");
  if(!m.classList.contains("open"))return;
  m.classList.remove("open");
  document.getElementById("ov").classList.remove("open");
  await pywebview.api.shrink_window();
}

/* ── Poll state from Python every 100ms ── */
let _ps="",_pc="",_pr=null,_pt="",_polling=false;
async function poll(){
  try{
    const s=await pywebview.api.get_state();
    if(!s)return;
    if(s.status!==_ps||s.color!==_pc){
      document.getElementById("st").textContent=s.status;
      document.getElementById("st").style.color=s.color;
      _ps=s.status;_pc=s.color;
    }
    if(s.rec!==_pr){
      document.getElementById("micSvg").style.display=s.rec?"none":"";
      document.getElementById("stopSvg").style.display=s.rec?"":"none";
      const b=document.getElementById("mic");
      if(s.rec)b.classList.add("on");else b.classList.remove("on");
      _pr=s.rec;
    }
    for(let i=0;i<s.levels.length;i++){
      const b=document.getElementById("b"+i);if(!b)continue;
      const v=Number(s.levels[i]),h=Math.max(3,Math.round(v*22));
      b.style.height=h+"px";
      if(s.rec){b.style.background=v>.7?"#4ade80":v>.02?"#0078d4":"var(--g2)"}
      else{b.style.background=v>.05?"#0078d4":"var(--g2)"}
    }
    if(s.transcript!==_pt){
      const el=document.getElementById("transcript");
      el.textContent=s.transcript;el.scrollTop=el.scrollHeight;
      _pt=s.transcript;
    }
    document.getElementById("chk_auto_type").innerHTML=s.auto_type?"&#10003;":"";
    document.getElementById("chk_close_to_tray").innerHTML=s.close_to_tray?"&#10003;":"";
    document.getElementById("chk_start_with_windows").innerHTML=s.start_with_windows?"&#10003;":"";
    document.getElementById("chk_start_minimized").innerHTML=s.start_minimized?"&#10003;":"";
    /* Update custom dropdown selected states */
    document.querySelectorAll('#csel_model_dd .csel-opt').forEach(o=>{
      if(o.dataset.val===s.cfg_model)o.classList.add('selected');else o.classList.remove('selected');
    });
    document.querySelectorAll('#csel_device_dd .csel-opt').forEach(o=>{
      if(o.dataset.val===s.cfg_device_mode)o.classList.add('selected');else o.classList.remove('selected');
    });
    const _ml={'tiny':'tiny (75 MB)','base':'base (142 MB)','small':'small (466 MB)','medium':'medium (1.5 GB)','large-v3':'large-v3 (3 GB)'};
    const _dl={'cpu/int8':'CPU \u2014 int8','cpu/float32':'CPU \u2014 float32','cuda/float16':'GPU \u2014 float16','cuda/int8':'GPU \u2014 int8'};
    const mv=document.getElementById('csel_model_val');if(mv)mv.textContent=_ml[s.cfg_model]||s.cfg_model;
    const dv=document.getElementById('csel_device_val');if(dv)dv.textContent=_dl[s.cfg_device_mode]||s.cfg_device_mode;
    const rb=document.getElementById("restart_btn");
    if(s.needs_restart)rb.classList.add("show");else rb.classList.remove("show");
    const wr=document.querySelector(".wrap");
    if(s.mini_mode)wr.classList.add("mini");else wr.classList.remove("mini");
    if(s.theme!==undefined&&s.theme!==_curTheme)applyTheme(s.theme);
  }catch(e){}
}
function startPolling(){if(_polling)return;_polling=true;setInterval(poll,100)}
window.addEventListener('pywebviewready',startPolling);
setTimeout(startPolling,2000);
window.addEventListener("blur",()=>{
  ddClose();
  setTimeout(poll,50);setTimeout(poll,200);setTimeout(poll,500);
});
window.addEventListener("focus",()=>{poll()});
document.getElementById("dragzone").addEventListener("dblclick",function(e){
  e.preventDefault();pywebview.api.toggle_mini();
});
document.getElementById("dragzone").addEventListener("pointerdown",function(){
  pywebview.api.drag_start();
});
window.addEventListener("pointerup",function(){
  pywebview.api.drag_end();
});
applyTheme($initial_theme);
</script></body></html>""")


class Api:
    def __init__(self, app):
        self._a = app

    def toggle_recording(self):
        self._a.toggle_recording()

    def close_app(self):
        self._a._on_close()

    def quit_app(self):
        self._a._on_quit()

    def restart_app(self):
        self._a._save_current_settings()
        try:
            subprocess.Popen([sys.executable] + sys.argv)
        except Exception:
            subprocess.Popen([sys.executable, os.path.join(APP_DIR, "voice_typer.py")])
        self._a._on_quit()

    def recalibrate(self):
        threading.Thread(target=self._a.calibrate, daemon=True).start()

    def toggle_mini(self):
        self._a._mini_mode = not self._a._mini_mode
        try:
            hwnd = self._a._own_hwnd
            target_w = WIN_W_MINI if self._a._mini_mode else WIN_W
            if hwnd:
                rect = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                self._a.window.resize(target_w, WIN_H)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, HWND_TOPMOST, rect.left, rect.top, 0, 0,
                    SWP_NOSIZE | SWP_NOACTIVATE,
                )
            else:
                self._a.window.resize(target_w, WIN_H)
        except Exception:
            pass

    def expand_window(self):
        self._a._menu_open = True
        self._a._set_alpha(ALPHA_ACTIVE)
        try:
            hwnd = self._a._own_hwnd
            if hwnd:
                rect = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                self._a.window.resize(WIN_W, WIN_H_EXPANDED)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, HWND_TOPMOST, rect.left, rect.top, 0, 0,
                    SWP_NOSIZE | SWP_NOACTIVATE,
                )
            else:
                self._a.window.resize(WIN_W, WIN_H_EXPANDED)
        except Exception:
            pass

    def shrink_window(self):
        self._a._menu_open = False
        try:
            target_w = WIN_W_MINI if self._a._mini_mode else WIN_W
            hwnd = self._a._own_hwnd
            if hwnd:
                rect = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                self._a.window.resize(target_w, WIN_H)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, HWND_TOPMOST, rect.left, rect.top, 0, 0,
                    SWP_NOSIZE | SWP_NOACTIVATE,
                )
            else:
                self._a.window.resize(target_w, WIN_H)
        except Exception:
            pass
        if not self._a.is_recording:
            self._a._schedule_fade()

    def drag_start(self):
        self._a._set_alpha(ALPHA_ACTIVE)

    def drag_end(self):
        if not self._a.is_recording:
            self._a._schedule_fade()

    def toggle_setting(self, key):
        if key == "auto_type":
            self._a.auto_type = not self._a.auto_type
        elif key == "close_to_tray":
            self._a.close_to_tray = not self._a.close_to_tray
        elif key == "start_minimized":
            self._a.start_minimized = not self._a.start_minimized
            if self._a.start_minimized:
                # Start minimized implies: start with Windows + close to tray
                self._a.close_to_tray = True
                if not self._a._startup_cached:
                    _set_startup(True)
                    self._a._startup_cached = True
            else:
                # Turning off start minimized also removes from startup
                if self._a._startup_cached:
                    _set_startup(False)
                    self._a._startup_cached = False
        elif key == "start_with_windows":
            enabled = not self._a._startup_cached
            _set_startup(enabled)
            self._a._startup_cached = enabled
        self._a._save_current_settings()

    def change_setting(self, key, value):
        if key == "model_size":
            self._a._cfg_model = value
            self._a._needs_restart = True
        elif key == "device_mode":
            self._a._cfg_device_mode = value
            self._a._needs_restart = True
        elif key == "theme":
            self._a._theme = int(value)
        self._a._save_current_settings()

    def get_state(self):
        return {
            "levels": [float(v) for v in self._a._wave_levels],
            "rec": self._a.is_recording,
            "status": self._a._status_text,
            "color": self._a._status_color,
            "transcript": self._a._transcript,
            "auto_type": self._a.auto_type,
            "close_to_tray": self._a.close_to_tray,
            "start_with_windows": self._a._startup_cached,
            "cfg_model": self._a._cfg_model,
            "cfg_device_mode": self._a._cfg_device_mode,
            "needs_restart": self._a._needs_restart,
            "mini_mode": self._a._mini_mode,
            "theme": self._a._theme,
            "start_minimized": self._a.start_minimized,
        }


class VoiceTyperApp:
    def __init__(self):
        self.sample_rate = SAMPLE_RATE
        self.block_size = int(self.sample_rate * 0.1)
        self.is_recording = False
        self.audio_buffer = []
        self.speech_detected = False
        self.silence_frames = 0
        self.silence_threshold = 0.01
        self.phrase_queue = queue.Queue()
        self.running = True
        self.lock = threading.Lock()
        self.tray_icon = None
        self.last_phrase_len = 0
        self.start_of_sentence = True
        self.model = None
        self.model_loaded = False
        self.stream = None
        self.current_rms = 0.0
        self.window = None
        self._started = False
        self.auto_type = True
        self.close_to_tray = False
        self._transcript = ""
        self._idle_frames = 0
        self._status_text = "Loading..."
        self._status_color = "#666"
        self._own_hwnd = 0
        self._last_fg_hwnd = 0
        self._startup_cached = _startup_enabled()
        self._peak_rms = 0.01
        self._needs_restart = False
        self._speech_frames = 0
        self._interim_typed_len = 0
        self._interim_typed_text = ""
        self._mini_mode = False
        self._fade_tag = 0
        self._menu_open = False
        self._theme = 0
        self.start_minimized = False

        self._wave_levels = collections.deque([0.0] * WAVE_BARS, maxlen=WAVE_BARS)
        self._voice_commands = sorted(
            VOICE_COMMANDS.items(), key=lambda x: len(x[0]), reverse=True
        )

        # Load saved settings — overrides config.py values
        settings = _load_settings()
        self.auto_type = settings.get("auto_type", True)
        self.close_to_tray = settings.get("close_to_tray", False)
        self._cfg_model = settings.get("model_size", MODEL_SIZE)
        self._cfg_device_mode = settings.get(
            "device_mode", f"{DEVICE}/{COMPUTE_TYPE}"
        )
        self._theme = settings.get("theme", 0)
        self.start_minimized = settings.get("start_minimized", False)

    # ─── Status ──────────────────────────────────────────────────────────

    @property
    def _dim_color(self):
        return _THEME_DIM[self._theme] if self._theme < len(_THEME_DIM) else '#666666'

    def _set_status(self, text, color="#666"):
        self._status_text = text
        self._status_color = color

    # ─── Win32 focus helpers ─────────────────────────────────────────────

    def _show_no_activate(self):
        """Show the window on top without stealing focus."""
        if self._own_hwnd:
            try:
                SW_SHOWNA = 8  # show without activating
                ctypes.windll.user32.ShowWindow(self._own_hwnd, SW_SHOWNA)
                ctypes.windll.user32.SetWindowPos(
                    self._own_hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE,
                )
                return
            except Exception:
                pass
        try:
            if self.window:
                self.window.show()
        except Exception:
            pass

    def _set_window_icon(self):
        """Set the taskbar/title-bar icon via Win32 SendMessage + LoadImage."""
        hwnd = self._own_hwnd
        if not hwnd:
            return
        # Need an .ico file for LoadImageW
        ico_path = os.path.join(BUNDLE_DIR, "icon.ico")
        if not os.path.exists(ico_path):
            return
        try:
            user32 = ctypes.windll.user32
            hicon_big = user32.LoadImageW(
                0, ico_path, IMAGE_ICON, 32, 32,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            hicon_small = user32.LoadImageW(
                0, ico_path, IMAGE_ICON, 16, 16,
                LR_LOADFROMFILE,
            )
            if hicon_big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
            if hicon_small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
        except Exception:
            pass

    def _set_alpha(self, alpha):
        """Set window opacity (0-255) via Win32 layered window."""
        hwnd = self._own_hwnd
        if not hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if not (style & WS_EX_LAYERED):
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
            user32.SetLayeredWindowAttributes(hwnd, 0, int(alpha), LWA_ALPHA)
        except Exception:
            pass

    def _fade_to_idle(self):
        """Gradually fade from active to idle opacity over ~0.3s."""
        steps = 10
        diff = ALPHA_ACTIVE - ALPHA_IDLE
        for i in range(1, steps + 1):
            if self.is_recording or self._menu_open or not self.running:
                return  # abort fade if recording started or menu open
            a = ALPHA_ACTIVE - int(diff * i / steps)
            self._set_alpha(a)
            time.sleep(0.03)

    def _schedule_fade(self):
        """Wait ALPHA_FADE_DELAY seconds then fade to idle."""
        tag = time.monotonic()
        self._fade_tag = tag

        def _do():
            time.sleep(ALPHA_FADE_DELAY)
            if self._fade_tag != tag or self.is_recording or self._menu_open:
                return
            self._fade_to_idle()
        threading.Thread(target=_do, daemon=True).start()

    def _track_foreground(self):
        user32 = ctypes.windll.user32
        while self.running:
            try:
                if not self._own_hwnd:
                    self._own_hwnd = user32.FindWindowW(None, "Whisper")
                fg = user32.GetForegroundWindow()
                if fg and fg != self._own_hwnd:
                    self._last_fg_hwnd = fg
            except Exception:
                pass
            time.sleep(0.15)

    def _restore_focus(self):
        if self._last_fg_hwnd:
            try:
                time.sleep(0.03)
                ctypes.windll.user32.SetForegroundWindow(self._last_fg_hwnd)
            except Exception:
                pass

    # ─── Wave update & auto-stop loop ────────────────────────────────────

    def _update_loop(self):
        while self.running:
            try:
                if self.is_recording:
                    rms = self.current_rms
                    self._peak_rms = max(self._peak_rms * 0.95, rms, 0.005)
                    lv = min(rms / self._peak_rms, 1.0)
                    self._wave_levels.append(lv)

                    idle_sec = (self._idle_frames * self.block_size) / self.sample_rate
                    if idle_sec >= AUTO_STOP_SECONDS:
                        self._stop_recording()
                else:
                    self._wave_levels = collections.deque(
                        [max(0, v - 0.08) for v in self._wave_levels],
                        maxlen=WAVE_BARS,
                    )
            except Exception:
                pass
            time.sleep(0.08)

    # ─── Sound effects ───────────────────────────────────────────────────

    def _play_sound(self, name):
        def _play():
            path = os.path.join(BUNDLE_DIR, f"{name}.wav")
            if os.path.exists(path):
                try:
                    winsound.PlaySound(
                        path, winsound.SND_FILENAME | winsound.SND_ASYNC
                    )
                    return
                except Exception:
                    pass
            winsound.Beep(800 if name == "start" else 400, 150)
        threading.Thread(target=_play, daemon=True).start()

    # ─── Engine ──────────────────────────────────────────────────────────

    def _load_model(self):
        cache_dir = MODELS_DIR

        model = self._cfg_model
        device, compute = self._cfg_device_mode.split("/")
        total_mb = _SIZES_MB.get(model, 0)

        # Track only the specific model's subdirectory, not all models
        model_subdir = os.path.join(
            cache_dir, f"models--Systran--faster-whisper-{model}"
        )

        def _model_dir_size():
            total = 0
            target = model_subdir
            if not os.path.isdir(target):
                return 0
            try:
                for root, _, files in os.walk(target):
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
            except OSError:
                pass
            return total

        initial_size = _model_dir_size()
        stop_monitor = threading.Event()

        def _monitor():
            while not stop_monitor.is_set():
                current = _model_dir_size()
                downloaded_mb = current / 1_048_576
                new_bytes = current - initial_size
                if new_bytes > 1_048_576 and total_mb > 0:
                    pct = min(downloaded_mb / total_mb * 100, 99)
                    self._set_status(
                        f"Downloading {model}... {pct:.0f}% "
                        f"({downloaded_mb:.0f}/{total_mb} MB)",
                        "#e0c060",
                    )
                stop_monitor.wait(0.5)

        self._set_status(f"Loading {model} model...", "#e0c060")
        monitor = threading.Thread(target=_monitor, daemon=True)
        monitor.start()

        try:
            self.model = WhisperModel(
                model, device=device, compute_type=compute,
                download_root=cache_dir,
            )
            stop_monitor.set()
            self._set_status(f"Initializing {model}...", "#e0c060")
            self.model_loaded = True
            self._set_status("Calibrating...", "#e0c060")
            self.calibrate()
            self._start_engine()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            print(f"\nModel load error: {exc}", flush=True)
            err = str(exc).lower()
            if device == "cuda" and ("cuda" in err or "cublas" in err
                                     or "cudnn" in err or "dll" in err
                                     or "ctranslate2" in err):
                self._set_status(
                    "CUDA error — falling back to CPU...", "#e0c060"
                )
                time.sleep(1)
                try:
                    self.model = WhisperModel(
                        model, device="cpu", compute_type="int8",
                        download_root=cache_dir,
                    )
                    stop_monitor.set()
                    self.model_loaded = True
                    self._cfg_device_mode = "cpu/int8"
                    self._needs_restart = False
                    self._save_current_settings()
                    self._set_status("Calibrating (CPU fallback)...", "#e0c060")
                    self.calibrate()
                    self._start_engine()
                except Exception as exc2:
                    self._set_status(f"Model error: {exc2}", "#e81123")
            else:
                self._set_status(f"Model error: {exc}", "#e81123")
        finally:
            stop_monitor.set()

    def calibrate(self):
        self._set_status("Calibrating...", "#e0c060")
        try:
            rec = sd.rec(
                int(self.sample_rate),
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                device=INPUT_DEVICE,
            )
            sd.wait()
            rms = np.sqrt(np.mean(rec ** 2))
            self.silence_threshold = max(rms * SILENCE_MULTIPLIER, 0.005)
            hk = HOTKEY.replace("windows", "Win").replace("+", "+").upper()
            self._set_status(f"{hk} to dictate", self._dim_color)
        except Exception:
            self._set_status("Mic error", "#e81123")

    def _start_engine(self):
        threading.Thread(target=self._transcription_worker, daemon=True).start()

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.block_size,
            device=INPUT_DEVICE,
            callback=self._audio_cb,
        )
        self.stream.start()

        # Global hotkey via Win32 RegisterHotKey (with keyboard library fallback)
        threading.Thread(target=self._hotkey_thread, daemon=True).start()

        hk = HOTKEY.replace("windows", "Win").replace("+", "+").upper()
        self._set_status(f"{hk} to dictate", "#666")

    def _hotkey_thread(self):
        user32 = ctypes.windll.user32
        mod, vk = _parse_hotkey(HOTKEY)
        MOD_NOREPEAT = 0x4000
        HOTKEY_ID = 1

        registered = bool(user32.RegisterHotKey(None, HOTKEY_ID, mod | MOD_NOREPEAT, vk))

        if not registered:
            # Fallback to keyboard library if RegisterHotKey fails
            try:
                keyboard.add_hotkey(HOTKEY, self.toggle_recording, suppress=False)
            except Exception:
                self._set_status("Hotkey error \u2014 run as admin", "#e81123")
            return

        msg = wintypes.MSG()
        while self.running:
            # Process all pending messages (not just WM_HOTKEY)
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.toggle_recording()
            time.sleep(0.05)

        user32.UnregisterHotKey(None, HOTKEY_ID)

    def _audio_cb(self, indata, frames, ti, status):
        if not self.is_recording:
            return

        chunk = indata[:, 0].copy()
        rms = np.sqrt(np.mean(chunk ** 2))
        self.current_rms = rms

        with self.lock:
            if rms > self.silence_threshold:
                self.speech_detected = True
                self.silence_frames = 0
                self._idle_frames = 0
                self.audio_buffer.append(chunk)
                self._speech_frames += 1
                # Interim transcription: snapshot every INTERIM_SECONDS
                speech_sec = (self._speech_frames * self.block_size) / self.sample_rate
                if speech_sec >= INTERIM_SECONDS and len(self.audio_buffer) > 0:
                    audio_snap = np.concatenate(self.audio_buffer)
                    self.phrase_queue.put(("interim", audio_snap))
                    self._speech_frames = 0
            elif self.speech_detected:
                self.audio_buffer.append(chunk)
                self.silence_frames += 1
                if (self.silence_frames * self.block_size) / self.sample_rate >= SILENCE_PAUSE:
                    self.phrase_queue.put(("final", np.concatenate(self.audio_buffer)))
                    self.audio_buffer = []
                    self.speech_detected = False
                    self.silence_frames = 0
                    self._speech_frames = 0
            else:
                self._idle_frames += 1

    def process_voice_commands(self, text):
        for phrase, repl in self._voice_commands:
            text = re.compile(re.escape(phrase), re.IGNORECASE).sub(repl, text)
        text = re.sub(r'\s+([.,!?;:\)\]\"])', r'\1', text)
        text = re.sub(r'([\(\[\"])\s+', r'\1', text)
        return re.sub(r'  +', ' ', text)

    def _remove_fillers(self, text):
        """Remove filler words (um, uh, like, you know)."""
        # Always-filler words (with optional trailing comma/period)
        text = re.sub(r'\b[Uu]m+\b[,.]?\s*', '', text)
        text = re.sub(r'\b[Uu]h+\b[,.]?\s*', '', text)
        text = re.sub(r'\b[Hh]mm+\b[,.]?\s*', '', text)
        text = re.sub(r'\b[Ee]h\b[,.]?\s*', '', text)
        # "like" as filler (between commas or at start with comma)
        text = re.sub(r',\s*like,', ',', text, flags=re.IGNORECASE)
        text = re.sub(r'^\s*like,\s*', '', text, flags=re.IGNORECASE)
        # "you know" as filler
        text = re.sub(r',\s*you know,\s*', ', ', text, flags=re.IGNORECASE)
        text = re.sub(r',\s*you know\s*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^\s*you know,?\s*', '', text, flags=re.IGNORECASE)
        # "I mean" as filler at start
        text = re.sub(r'^\s*I mean,?\s*', '', text, flags=re.IGNORECASE)
        # Clean up double spaces and orphaned commas
        text = re.sub(r',\s*,', ',', text)
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)
        return text.strip()

    def auto_capitalize(self, text):
        if not AUTO_CAPITALIZE:
            return text
        if self.start_of_sentence and text:
            text = text[0].upper() + text[1:]
        text = re.sub(
            r'([.!?]\s+)([a-z])',
            lambda m: m.group(1) + m.group(2).upper(),
            text,
        )
        s = text.rstrip()
        self.start_of_sentence = bool(s and s[-1] in '.!?\n')
        return text

    def handle_action(self, action):
        if action == ACTION_BACKSPACE:
            keyboard.press_and_release("backspace")
        elif action == ACTION_DELETE_PHRASE:
            for _ in range(self.last_phrase_len):
                keyboard.press_and_release("backspace")
                time.sleep(0.005)
            self.last_phrase_len = 0
        elif action == ACTION_UNDO:
            keyboard.press_and_release("ctrl+z")
        elif action == ACTION_SELECT_ALL:
            keyboard.press_and_release("ctrl+a")

    def _backspace(self, n):
        """Send n backspace key presses to erase interim text."""
        if n <= 0:
            return
        for _ in range(n):
            keyboard.press_and_release("backspace")
            time.sleep(0.003)

    def _revert_status(self):
        hk = HOTKEY.replace("windows", "Win").replace("+", "+").upper()
        if self.is_recording:
            self._set_status("Listening...", "#e0e0e0")
        else:
            self._set_status(f"{hk} to dictate", self._dim_color)

    def _transcription_worker(self):
        while self.running:
            try:
                item = self.phrase_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # Drain queue — skip stale interims, but stop at a final
            if item[0] == "interim":
                while True:
                    try:
                        newer = self.phrase_queue.get_nowait()
                        item = newer
                        if newer[0] == "final":
                            break
                    except queue.Empty:
                        break

            tag, audio = item
            is_interim = (tag == "interim")

            if is_interim:
                self._set_status("...", "#555")
            else:
                self._set_status("...", "#e0c060")

            try:
                if is_interim:
                    # Fast settings for interim (greedy, no beam search)
                    segs, _ = self.model.transcribe(
                        audio, language=LANGUAGE, beam_size=1,
                        vad_filter=True, no_speech_threshold=0.6,
                        condition_on_previous_text=False,
                    )
                else:
                    # Full quality for final
                    segs, _ = self.model.transcribe(
                        audio, language=LANGUAGE, beam_size=5,
                        vad_filter=True, no_speech_threshold=0.6,
                        condition_on_previous_text=False,
                    )
                text = "".join(s.text for s in segs).strip()
                if not text:
                    if not is_interim:
                        self._revert_status()
                    else:
                        self._set_status("Listening...", "#e0e0e0")
                    continue

                text = self.process_voice_commands(text)
                text = self._remove_fillers(text)

                if not is_interim:
                    # Voice command actions only on final
                    stripped = text.strip()
                    if stripped in (ACTION_BACKSPACE, ACTION_DELETE_PHRASE,
                                    ACTION_UNDO, ACTION_SELECT_ALL):
                        if self._interim_typed_len > 0 and self.auto_type:
                            self._backspace(self._interim_typed_len)
                            self._interim_typed_len = 0
                            self._interim_typed_text = ""
                        self.handle_action(stripped)
                        self._revert_status()
                        continue

                    for ac in (ACTION_BACKSPACE, ACTION_DELETE_PHRASE,
                               ACTION_UNDO, ACTION_SELECT_ALL):
                        text = text.replace(ac, "")
                    text = text.strip()
                    if not text:
                        self._revert_status()
                        continue

                if is_interim:
                    # Don't let interim change start_of_sentence permanently
                    saved_sos = self.start_of_sentence
                    text = self.auto_capitalize(text)
                    self.start_of_sentence = saved_sos
                else:
                    text = self.auto_capitalize(text)

                if not text.endswith("\n"):
                    text += " "

                if is_interim:
                    if self.auto_type:
                        if self._interim_typed_len > 0:
                            self._backspace(self._interim_typed_len)
                        self._paste_text(text)
                    self._interim_typed_len = len(text) if self.auto_type else 0
                    self._interim_typed_text = text
                    self._set_status("Listening...", "#e0e0e0")
                else:
                    # Final: replace interim with final text
                    if self._interim_typed_len > 0 and self.auto_type:
                        # Normalize to compare content, not formatting
                        _in = re.sub(r'\s+', ' ', self._interim_typed_text.strip().lower())
                        _fn = re.sub(r'\s+', ' ', text.strip().lower())
                        if _in == _fn:
                            # Same content — keep interim as-is
                            pass
                        else:
                            self._backspace(self._interim_typed_len)
                            self._paste_text(text)
                    elif self.auto_type:
                        self._paste_text(text)
                    self._interim_typed_len = 0
                    self._interim_typed_text = ""
                    self._transcript += text

                    d = text.strip()
                    if len(d) > 30:
                        d = d[:30] + "..."
                    self._set_status(d, "#e0e0e0")
                    threading.Thread(
                        target=lambda: (time.sleep(2), self._revert_status()),
                        daemon=True,
                    ).start()

            except RuntimeError as exc:
                err = str(exc).lower()
                print(f"[VT] Transcription error: {exc}", flush=True)
                if "cublas" in err or "cuda" in err or "cudnn" in err or "dll" in err:
                    self._set_status("CUDA error — reloading on CPU...", "#e0c060")
                    try:
                        cache_dir = MODELS_DIR
                        self.model = WhisperModel(
                            self._cfg_model, device="cpu", compute_type="int8",
                            download_root=cache_dir,
                        )
                        self._cfg_device_mode = "cpu/int8"
                        self._needs_restart = False
                        self._save_current_settings()
                        self._revert_status()
                    except Exception as exc2:
                        self._set_status(f"Model error: {exc2}", "#e81123")
                else:
                    self._set_status("Error", "#e81123")
                    threading.Thread(
                        target=lambda: (time.sleep(3), self._revert_status()),
                        daemon=True,
                    ).start()
            except Exception as exc:
                print(f"[VT] Transcription error: {exc}", flush=True)
                self._set_status("Error", "#e81123")
                threading.Thread(
                    target=lambda: (time.sleep(3), self._revert_status()),
                    daemon=True,
                ).start()

    def _paste_text(self, text):
        self.last_phrase_len = len(text)
        try:
            old = pyperclip.paste()
        except Exception:
            old = ""

        pyperclip.copy(text)
        time.sleep(0.02)
        keyboard.press_and_release("ctrl+v")
        time.sleep(0.05)

        def restore():
            time.sleep(1.0)
            try:
                pyperclip.copy(old)
            except Exception:
                pass
        threading.Thread(target=restore, daemon=True).start()

    def toggle_recording(self):
        if not self.model_loaded:
            return
        self._show_no_activate()

        if self.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

        threading.Thread(target=self._restore_focus, daemon=True).start()

    def _start_recording(self):
        self.is_recording = True
        self._peak_rms = 0.01
        with self.lock:
            self.audio_buffer = []
            self.speech_detected = False
            self.silence_frames = 0
            self._idle_frames = 0
            self._speech_frames = 0
        self._interim_typed_len = 0
        self._interim_typed_text = ""

        self._play_sound("mic_on")
        self._set_status("Listening...", "#e0e0e0")
        self._set_alpha(ALPHA_ACTIVE)
        self._update_tray()

    def _stop_recording(self):
        if not self.is_recording:
            return
        with self.lock:
            if self.audio_buffer and self.speech_detected:
                self.phrase_queue.put(("final", np.concatenate(self.audio_buffer)))
                self.audio_buffer = []
            self.is_recording = False
            self.speech_detected = False
            self.silence_frames = 0
            self._idle_frames = 0
            self._speech_frames = 0

        self._play_sound("mic_off")
        self._revert_status()
        self._schedule_fade()
        self._update_tray()

    # ─── System Tray ─────────────────────────────────────────────────────

    def _tray_image(self, rec=False):
        # Use the app icon for idle; red-tinted version for recording
        if not hasattr(self, "_tray_icon_idle"):
            try:
                self._tray_icon_idle = Image.open(ICON_PATH).resize(
                    (64, 64), Image.LANCZOS
                )
            except Exception:
                s = 64
                img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
                ImageDraw.Draw(img).ellipse([4, 4, s - 4, s - 4], fill="#2a2a2a")
                self._tray_icon_idle = img
            # Build red recording variant: overlay with red tint
            rec_img = self._tray_icon_idle.copy().convert("RGBA")
            overlay = Image.new("RGBA", rec_img.size, (220, 30, 30, 140))
            rec_img = Image.alpha_composite(rec_img, overlay)
            self._tray_icon_rec = rec_img
        return self._tray_icon_rec if rec else self._tray_icon_idle

    def _update_tray(self):
        if not self.tray_icon:
            return
        try:
            self.tray_icon.icon = self._tray_image(self.is_recording)
            self.tray_icon.title = (
                "Whisper \u2014 Recording" if self.is_recording else "Whisper"
            )
        except Exception:
            pass

    def _setup_tray(self):
        if not ENABLE_TRAY_ICON:
            return
        try:
            import pystray
        except ImportError:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda *_: self._show_from_tray()),
            pystray.MenuItem(
                "Toggle Recording", lambda *_: self.toggle_recording()
            ),
            pystray.MenuItem(
                "Recalibrate",
                lambda *_: threading.Thread(
                    target=self.calibrate, daemon=True
                ).start(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda *_: self._on_quit()),
        )
        tray_img = self._tray_image()
        self.tray_icon = pystray.Icon(
            "whisper", tray_img, "Whisper", menu
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _show_from_tray(self):
        try:
            if self.window:
                self.window.show()
                self.window.on_top = True
        except Exception:
            pass

    # ─── Lifecycle ───────────────────────────────────────────────────────

    def _on_loaded(self):
        if self._started:
            return
        self._started = True

        # Find our window handle immediately
        try:
            self._own_hwnd = ctypes.windll.user32.FindWindowW(None, "Whisper")
        except Exception:
            pass

        self._set_window_icon()
        self._setup_tray()
        self._set_alpha(ALPHA_IDLE)
        threading.Thread(target=self._load_model, daemon=True).start()
        threading.Thread(target=self._update_loop, daemon=True).start()
        threading.Thread(target=self._track_foreground, daemon=True).start()

    def _save_current_settings(self):
        try:
            data = {
                "version": VERSION,
                "auto_type": self.auto_type,
                "close_to_tray": self.close_to_tray,
                "model_size": self._cfg_model,
                "device_mode": self._cfg_device_mode,
                "theme": self._theme,
                "start_minimized": self.start_minimized,
            }
            try:
                data["x"] = self.window.x
                data["y"] = self.window.y
            except Exception:
                pass
            _save_settings(data)
        except Exception:
            pass

    def _on_close(self):
        if self.close_to_tray:
            self._save_current_settings()
            try:
                self.window.hide()
            except Exception:
                pass
            return
        self._on_quit()

    def _on_quit(self):
        self._save_current_settings()
        self.running = False
        self.is_recording = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        try:
            if self.window:
                self.window.destroy()
        except Exception:
            pass

    def run(self):
        t = _THEME_COLORS[self._theme] if self._theme < len(_THEME_COLORS) else _THEME_COLORS[0]
        html = HTML.substitute(
            wave_bars=WAVE_BARS,
            initial_theme=self._theme,
            g1=t[0], g2=t[1], g3=t[2], g4=t[3],
        )

        screen_w = _screen_width()
        settings = _load_settings()
        x = settings.get("x", (screen_w - WIN_W) // 2)
        y = settings.get("y", 8)

        api = Api(self)
        self.window = webview.create_window(
            "Whisper",
            html=html,
            width=WIN_W,
            height=WIN_H,
            x=x,
            y=y,
            frameless=True,
            on_top=True,
            js_api=api,
            resizable=False,
            min_size=(100, 36),
            background_color=t[0],
            hidden=self.start_minimized,
        )
        self.window.events.loaded += lambda: self._on_loaded()
        _icon = ICON_PATH if os.path.exists(ICON_PATH) else None
        webview.start(debug=False, icon=_icon)


if __name__ == "__main__":
    try:
        app = VoiceTyperApp()
        app.run()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nError: {e}")
        print("Make sure your microphone is connected and drivers are installed.")
        input("Press Enter to exit...")
        sys.exit(1)
