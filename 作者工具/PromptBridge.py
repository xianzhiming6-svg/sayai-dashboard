#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PromptBridge 桌面面板 v1.1
- 翻译、弹选项、补充、单一/多模式、🎤录音转文字
"""
import webview, json, urllib.request, os, re, subprocess, platform, threading, socket, shutil
from license import check_and_count as _check_license, get_install_id as _install_id, activate as _activate
from reporter import report_usage as _report

MODEL = "deepseek-v4-flash"
# 安全代理：翻译请求发到 Render 服务器，API Key 只在服务端
API_URL = "https://sayai-dashboard.onrender.com/translate"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(os.path.expanduser("~/Library/Application Support/说AI懂的话/记忆本"))
OLD_MEMORY_DIR = os.path.join(os.path.expanduser("~/Documents/说AI懂的话/记忆本"))
os.makedirs(MEMORY_DIR, exist_ok=True)
# 首次启动时把旧位置（文稿/说AI懂的话/记忆本）里的项目迁移过来
try:
    if not os.listdir(MEMORY_DIR) and os.path.isdir(OLD_MEMORY_DIR):
        for f in os.listdir(OLD_MEMORY_DIR):
            if f.endswith(".json"):
                try: shutil.copy2(os.path.join(OLD_MEMORY_DIR, f), os.path.join(MEMORY_DIR, f))
                except Exception: pass
except Exception:
    pass
IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"

try:
    from opencc import OpenCC as _OpenCC
    _cc = _OpenCC("t2s")
    def to_simplified(text):
        try: return _cc.convert(text)
        except Exception: return text
except Exception:
    def to_simplified(text): return text

_lock_socket = None

def _acquire_single_instance():
    """同一时间只允许一个窗口：第二个启动的实例直接退出"""
    global _lock_socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 47837))
        s.listen(1)
    except OSError:
        s.close()
        return False
    _lock_socket = s
    return True

INTENT_SYS = """你是"白话精炼器"。用户用日常口语说出需求（可能有语音转文字带来的错别字），你把这段话重写成一条能直接喂给 AI 执行的精准指令。

规则：
1. 保持用户意图不变，把模糊表达换为精确术语，补齐省略的细节。
2. 输出可以直接复制粘贴给任何 AI Agent，让它第一轮就理解完整需求。
3. 废话丢弃：自我怀疑、重复啰嗦、过程描述。
4. 遇到歧义词或模糊指代，末尾标注【拿不准：XXX是指？】选项：A. ... B. ... C. ...

输出格式：先给出指令内容，然后用一行"---"分隔，最后用【回译：】开头写通俗语言版本。
如果用户的话里有歧义或关键信息缺失（比如"那个文件""这个东西""买苹果"分不清指什么），必须在上面的完整输出之后，单独再输出一行：
【拿不准：XXX是指？】选项：A. ... B. ... C. ...
（注意：这一行必须单独成行，不能写进精准指令正文；没有歧义就绝对不要输出）

示例：
请为夏季促销设计手机端海报方案：1.推荐3款零基础工具 2.促销海报尺寸 3.色彩搭配 4.文案结构 5.步骤
---
【回译：】我帮你理解：你是要做个夏天促销的海报，不想用PS，想用手机就能做的简单工具。帮你列出App、尺寸、配色、文案、步骤。"""

def call_deepseek(messages, max_tokens=900):
    """通过 Render 服务器安全代理调用 DeepSeek（Key 在服务端，客户端不可见）"""
    payload = {"model": MODEL, "messages": messages}
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    if "error" in r:
        raise RuntimeError(r["error"])
    return r["content"], r["tokens"]

def parse_uncertain(text):
    body = text; uncertain = None; options = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if "【拿不准" in line:
            uncertain = line.strip()
            # 从这一行提取选项（可能同行，也可能后续行）
            all_options_text = uncertain
            # 先看后续行有没有 A. B. C.
            for j in range(i+1, min(i+6, len(lines))):
                ol = lines[j].strip()
                if re.match(r'^[A-C][.．、]', ol):
                    options.append(re.sub(r'^[A-C][.．、]\s*', '', ol).strip().rstrip("。"))
                    all_options_text += "\n" + ol
                elif ol == '' and not options: continue
                elif options: break
            # 如果后续行没找到，从 uncertain 行本身提取（同行格式）
            if not options:
                # 找 "？—" 或 "是指—" 或 "选项：" 后面的部分
                m = re.search(r'[？?]\s*[—\-]\s*(.*)', uncertain)
                if not m: m = re.search(r'选项[：:]\s*(.*)', uncertain)
                if m:
                    part = m.group(1)
                    # 按 A. B. C. 分割
                    parts = re.split(r'\s*[A-C][.．、]\s*', part)
                    options = [p.strip().rstrip("。").rstrip("？") for p in parts[1:] if p.strip()][:3]
            # 如果还找不到，尝试从整行用 split
            if not options:
                parts = re.split(r'[A-C][.．、]\s*', uncertain)
                options = [p.strip().rstrip("。").rstrip("？") for p in parts[1:] if p.strip()][:3]
            # 构造 body（去掉拿不准行和选项行）
            end = i + 1
            for j in range(i+1, min(i+6, len(lines))):
                if re.match(r'^[A-C][.．、]', lines[j].strip()): end = j + 1
                elif lines[j].strip() and not re.match(r'^[A-C][.．、]', lines[j].strip()): break
            body = "\n".join(lines[:i] + lines[end:])
            break
    return body, uncertain, options[:3]

def load_memory(project):
    try:
        with open(os.path.join(MEMORY_DIR, f"{project}.json")) as f: return json.load(f)
    except Exception: return {"指代": {}, "纠错": {}, "最近使用": []}

def save_memory(project, mem):
    if len(mem.get("指代", {})) > 200:
        keys = list(mem["指代"].keys())
        for k in keys[:len(keys)-200]: del mem["指代"][k]
    with open(os.path.join(MEMORY_DIR, f"{project}.json"), "w") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)

def list_projects():
    return sorted([f[:-5] for f in os.listdir(MEMORY_DIR) if f.endswith(".json")]) or ["默认项目"]

class Api:
    def __init__(self):
        self.current_project = "默认项目"
        self.current_memory = load_memory(self.current_project)
        self._recording = False
        self._audio_chunks = []
        self._rec_fs = 16000
        self._rec_stream = None
        # 恢复上次关闭时的项目
        try:
            _sf = os.path.join(os.path.dirname(MEMORY_DIR), "state.json")
            if os.path.isfile(_sf):
                with open(_sf) as f: _s = json.load(f)
                p = _s.get("project", "")
                if p and os.path.isfile(os.path.join(MEMORY_DIR, p + ".json")):
                    self.current_project = p
                    self.current_memory = load_memory(p)
        except Exception: pass
    
    def get_saved_project(self):
        return self.current_project

    def translate(self, original, supplement, project_name, mode):
        # 授权检查
        ok, rem, msg = _check_license()
        if not ok:
            return {"ok": False, "error": msg, "need_activate": True}
        # 正常翻译逻辑
        combined = original
        if supplement.strip():
            combined = f"{original}\n\n补充：{supplement.strip()}"
            if mode == "project":
                self.save_to_memory(original, project_name)
        mem_hint = ""
        if mode == "project":
            if project_name != self.current_project:
                self.current_project = project_name
                self.current_memory = load_memory(project_name)
                # 保存当前项目到状态文件，关闭窗口重开后恢复
                try:
                    _sdir = os.path.dirname(MEMORY_DIR)
                    os.makedirs(_sdir, exist_ok=True)
                    with open(os.path.join(_sdir, "state.json"), "w") as f:
                        json.dump({"project": project_name}, f)
                except Exception: pass
            mem = self.current_memory
            for w, t in mem.get("指代", {}).items():
                if w in combined: combined = combined.replace(w, t)
            recent = mem.get("最近使用", [])[:3]
            if recent: mem_hint = f"\n（上下文：{'; '.join(recent)}）"
        try:
            instruction, tokens = call_deepseek([
                {"role": "system", "content": INTENT_SYS},
                {"role": "user", "content": f"用户的话：{combined}{mem_hint}"}])
            body, uncertain, options = parse_uncertain(instruction)
            body = to_simplified(body)
            if uncertain: uncertain = to_simplified(uncertain)
            options = [to_simplified(o) for o in options]
            # 后台静默上报用量
            try:
                threading.Thread(target=_report,
                    args=(_install_id, tokens), daemon=True).start()
            except Exception: pass
            return {"ok": True, "body": body, "uncertain": uncertain, "options": options, "tokens": tokens}
        except Exception as e: return {"ok": False, "error": str(e)}

    def get_install_id_api(self):
        return _install_id()
    
    def activate(self, code):
        ok, msg = _activate(code)
        return {"ok": ok, "msg": msg}
    
    def save_action(self, project_name, original, instruction):
        try:
            mem = load_memory(project_name) if project_name != self.current_project else self.current_memory
            mem.setdefault("最近使用", []).insert(0, original[:40] + "…" if len(original) > 40 else original)
            mem["最近使用"] = mem["最近使用"][:20]
            save_memory(project_name, mem); return True
        except Exception: return False

    def apply_option(self, original, supplement, option, project_name, mode):
        self.save_to_memory(original, project_name)
        return self.translate(original, supplement.strip() + "\n（我选：" + option + "）", project_name, mode)

    def save_to_memory(self, text, project_name):
        """保存原话到记忆本。只在用户有交互价值时调用。"""
        try:
            mem = load_memory(project_name)
            mem.setdefault("最近使用", []).insert(0, text[:60])
            mem["最近使用"] = mem["最近使用"][:20]
            save_memory(project_name, mem)
        except Exception: pass

    def check_update(self):
        """检查最新版本。先查 Render 服务器，失败查 GitHub Release。"""
        try:
            import urllib.request, json
            req = urllib.request.Request("https://sayai-dashboard.onrender.com/version",
                headers={"User-Agent": "sayai"})
            d = json.loads(urllib.request.urlopen(req, timeout=8).read())
            v = d.get("version", "")
            is_mac = platform.system() == "Darwin"
            url = d.get("mac_url") if is_mac else d.get("win_url")
            if v: return {"ok": True, "latest": v, "url": url or ""}
        except Exception: pass
        try:
            import urllib.request, json
            req = urllib.request.Request(
                "https://api.github.com/repos/xianzhiming6-svg/sayai-dashboard/releases/latest",
                headers={"User-Agent": "sayai"})
            r = json.loads(urllib.request.urlopen(req, timeout=8).read())
            v = (r.get("tag_name") or "").lstrip("v")
            if not v: return {"ok": False, "latest": "", "url": ""}
            is_mac = platform.system() == "Darwin"
            url = ""
            for a in r.get("assets", []):
                n = a.get("name", "").lower()
                if is_mac and "mac" in n: url = a["browser_download_url"]; break
                if not is_mac and "win" in n: url = a["browser_download_url"]; break
            return {"ok": True, "latest": v, "url": url}
        except Exception: return {"ok": False, "latest": "", "url": ""}

    def do_update(self, url):
        """下载+替换+重启，全自动。"""
        try:
            import tempfile, zipfile, shutil, subprocess
            tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
            urllib.request.urlretrieve(url, tmp.name)
            td = tempfile.mkdtemp()
            with zipfile.ZipFile(tmp.name, 'r') as z: z.extractall(td)
            os.unlink(tmp.name)
            is_mac = platform.system() == "Darwin"
            target = None
            for root, dirs, files in os.walk(td):
                for d in dirs:
                    if (is_mac and d.endswith(".app")) or (not is_mac and d.endswith(".exe")):
                        target = os.path.join(root, d); break
                if target: break
            if not target: return {"ok": False, "error": "安装包格式不对"}
            import sys
            if getattr(sys, 'frozen', False):
                cur = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(sys.executable))))
            else: cur = os.path.abspath(".")
            if is_mac:
                s = tempfile.NamedTemporaryFile(suffix=".sh", mode="w", delete=False)
                s.write(f'#!/bin/bash\nsleep 2\nrm -rf "{cur}"\nmv "{target}" "{cur}"\nopen "{cur}"\nrm "$0"\n')
                s.close(); os.chmod(s.name, 0o755)
                subprocess.Popen(["/usr/bin/open", "-a", "Terminal", s.name])
            else:
                s = tempfile.NamedTemporaryFile(suffix=".bat", mode="w", delete=False)
                s.write(f'@echo off\ntimeout /t 2 /nobreak >nul\nrmdir /s /q "{cur}"\nmove "{target}" "{cur}"\nstart "" "{cur}"\ndel "%~f0"\n')
                s.close(); subprocess.Popen(["cmd", "/c", s.name])
            os._exit(0)
        except Exception as e: return {"ok": False, "error": str(e)}

    def copy_to_clipboard(self, text):
        try:
            if IS_MAC:
                try:
                    from AppKit import NSPasteboard, NSPasteboardTypeString
                    pb = NSPasteboard.generalPasteboard()
                    pb.clearContents()
                    pb.setString_forType_(text, NSPasteboardTypeString)
                    return True
                except Exception:
                    p = subprocess.run(["/usr/bin/pbcopy"], input=text.encode("utf-8"),
                        capture_output=True, timeout=10)
                    return p.returncode == 0
            elif IS_WIN:
                import ctypes
                CF_UNICODETEXT = 13
                GMEM_MOVEABLE = 0x0002
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                if not user32.OpenClipboard(0):
                    return False
                try:
                    user32.EmptyClipboard()
                    data = text.encode("utf-16-le") + b"\x00\x00"
                    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                    if h:
                        p = kernel32.GlobalLock(h)
                        ctypes.memmove(p, data, len(data))
                        kernel32.GlobalUnlock(h)
                        user32.SetClipboardData(CF_UNICODETEXT, h)
                finally:
                    user32.CloseClipboard()
                return True
            return True
        except Exception: return False

    def get_projects(self): return list_projects()

    def create_project(self, name):
        p = os.path.join(MEMORY_DIR, f"{name}.json")
        if os.path.exists(p): return False
        save_memory(name, {"指代": {}, "纠错": {}, "最近使用": []}); return True

    def delete_project(self, name):
        """删除项目：连同它的记忆文件一起删除"""
        try:
            if not name or name == "默认项目": return False
            p = os.path.join(MEMORY_DIR, f"{name}.json")
            if os.path.exists(p): os.remove(p)
            if self.current_project == name:
                self.current_project = "默认项目"
                self.current_memory = load_memory("默认项目")
            return True
        except Exception:
            return False

    def save_reference(self, project_name, word, choice):
        """长项目模式：记住'某个词/指代'对应什么，下次自动替换"""
        try:
            mem = load_memory(project_name) if project_name != self.current_project else self.current_memory
            mem.setdefault("指代", {})[word.strip()] = choice.strip()
            save_memory(project_name, mem)
            return True
        except Exception:
            return False

    def start_voice(self):
        """点击麦克风：开始或停止录音"""
        if self._recording: return self._stop_and_recognize()
        else: return self._start_recording()

    def _start_recording(self):
        import sys as _sys; _saved = list(_sys.path)
        try:
            for p in list(_sys.path):
                if 'venv' in p or 'hermes-agent' in p: _sys.path.remove(p)
            import sounddevice as sd
            self._audio_chunks = []; self._rec_fs = 16000
            self._rec_start_time = __import__('time').time()
            def callback(indata, frames, time, status):
                self._audio_chunks.append(indata.copy())
                if __import__('time').time() - self._rec_start_time > 300:
                    self._rec_stream.stop()
            self._rec_stream = sd.InputStream(samplerate=self._rec_fs, channels=1, dtype='int16', callback=callback)
            self._rec_stream.start(); self._recording = True
            return {"ok": True, "recording": True}
        except Exception as e: return {"ok": False, "error": str(e)}
        finally: _sys.path[:] = _saved

    def _stop_and_recognize(self):
        import sys as _sys; _saved = list(_sys.path)
        try:
            for p in list(_sys.path):
                if 'venv' in p or 'hermes-agent' in p: _sys.path.remove(p)
            import numpy as np, tempfile, wave
            self._rec_stream.stop(); self._rec_stream.close(); self._recording = False
            if not self._audio_chunks: return {"ok": False, "error": "没有录到声音"}
            audio = np.concatenate(self._audio_chunks)
            peak = float(np.abs(audio).max())
            if peak < 800:
                return {"ok": False, "error": "没有检测到声音：请检查麦克风是否插好，并确认系统设置→声音→输入里选对了设备"}
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            with wave.open(tmp.name, 'wb') as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(self._rec_fs)
                wf.writeframes(audio.tobytes())
            # faster-whisper 本地识别（base 模型，中文优化）
            from faster_whisper import WhisperModel
            model_dir = os.path.join(APP_DIR, "whisper-base")
            if os.path.isdir(model_dir):
                model = WhisperModel(model_dir, device="cpu", compute_type="int8", local_files_only=True)
            else:
                model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(tmp.name, language="zh", beam_size=5,
                vad_filter=True, initial_prompt="以下是普通话的简体中文语音转写。")
            text = "".join(seg.text for seg in segments)
            text = to_simplified(text)
            os.unlink(tmp.name)
            if not text.strip(): return {"ok": False, "error": "未识别到语音，请靠近麦克风再说一次"}
            return {"ok": True, "text": text}
        except Exception as e: return {"ok": False, "error": str(e)}
        finally: _sys.path[:] = _saved

api = Api()

# noinspection PyUnusedLocal
HTML = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
body{background:#1e1e1e;color:#e8e8e8;height:100vh;display:flex;flex-direction:column}
.header{background:#252526;padding:10px 14px;display:flex;justify-content:space-between;align-items:center}
.header .title{font-size:14px;font-weight:700}.header .sub{font-size:10px;color:#9d9d9d}
.mode-bar{background:#2d2d30;padding:6px 14px;display:flex;gap:10px;align-items:flex-end;font-size:11px;color:#9d9d9d}
.mode-field{display:flex;flex-direction:column;gap:3px}
.mode-field label{font-size:11px;color:#9d9d9d}
.mode-bar select{background:#3a3a3c;color:#e8e8e8;border:1px solid #555;border-radius:4px;padding:3px 6px;font-size:11px}
.mode-bar button{background:#3a3a3c;color:#e8e8e8;border:1px solid #555;border-radius:4px;padding:3px 8px;font-size:10px;cursor:pointer}
.content{flex:1;display:flex;flex-direction:column;padding:10px 14px;overflow-y:auto}
label{font-size:11px;color:#9d9d9d;margin-bottom:2px;display:block}
textarea{width:100%;background:#2d2d30;color:#e8e8e8;border:1px solid #3a3a3c;border-radius:6px;padding:8px;font-size:13px;resize:none;outline:none}
textarea:focus{border-color:#0a84ff}
#inputBox{height:85px;margin-bottom:6px}#supplementBox{height:36px;margin-bottom:8px}
.btn-row{display:flex;gap:8px;margin-bottom:8px;align-items:center}
button{padding:6px 16px;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer}
#btnTranslate{background:#0a84ff;color:white}#btnTranslate:hover{background:#409cff}
#btnCopy{background:#30d158;color:white}#btnCopy:hover{background:#53d769}
#btnCopy:disabled{background:#3a3a3c;color:#777;cursor:not-allowed}
#btnVoice{width:24px;height:24px;border-radius:50%;background:transparent;color:#9d9d9d;border:1px solid #555;font-size:10px;padding:0;display:inline-flex;align-items:center;justify-content:center;vertical-align:middle;margin-right:2px}
#btnVoice:hover{color:#e8e8e8;border-color:#0a84ff}
#activateBox{display:none;background:#2d1b4e;border-radius:8px;padding:12px;margin:8px 0;text-align:center}
#activateBox p{color:#c4a0ff;font-size:11px;margin-bottom:8px}
#activateBox input{background:#3a3a3c;color:#e8e8e8;border:1px solid #7c5ce7;border-radius:4px;padding:6px 10px;font-size:12px;width:200px;text-align:center}
#activateBox button{background:#7c5ce7;color:#fff;padding:6px 14px;border-radius:4px;font-size:11px;margin-left:6px}
#activateBox .msg{color:#ff6b6b;font-size:10px;margin-top:6px}
.status{margin-left:auto;font-size:10px;color:#9d9d9d}
.uncertain{display:none;background:#3a2e00;border-radius:6px;padding:8px 10px;margin-bottom:8px}
.uncertain .q{color:#ffd60a;font-size:11px;margin-bottom:5px}
.uncertain .opts{display:flex;gap:6px;flex-wrap:wrap}
.uncertain .opt{background:#4a3d00;color:#ffd60a;border:none;padding:4px 10px;border-radius:4px;font-size:11px;cursor:pointer}
.uncertain .opt:hover{background:#5a4d00}
.result-label{font-size:11px;color:#9d9d9d;margin-bottom:2px}
#resultBox{flex:1;background:#2d2d30;border:1px solid #3a3a3c;border-radius:6px;padding:10px;font-size:13px;line-height:1.6;white-space:pre-wrap;overflow-y:auto;min-height:180px}
</style></head><body>
<div class="header"><span class="title">说AI懂的话</span><span class="sub">白话 → AI能懂的话</span><button id="btnUpdate" title="检查更新" style="margin-left:auto;background:transparent;color:#9d9d9d;border:1px solid #555;padding:2px 8px;border-radius:4px;font-size:10px;cursor:pointer">更新</button></div>
<div id="updateBar" style="display:none;background:#2d2d00;border-bottom:1px solid #555;padding:6px 14px;font-size:11px;color:#ffd60a">发现新版本 v<span id="updateVer"></span> — <a id="updateLink" style="color:#ffd60a;cursor:pointer;text-decoration:underline" onclick="doUpdate()">点击自动更新</a></div>
<div class="mode-bar">
  <div class="mode-field">
    <label for="modeSelect">模式</label>
    <select id="modeSelect"><option value="single">单次（翻译完即丢）</option><option value="project">长项目（本地记忆）</option></select>
  </div>
  <select id="projectSelect"></select>
  <button id="btnNewProject">+新建项目</button>
  <button id="btnDelProject">删除项目</button>
</div>
<div class="content">
  <label for="inputBox">你的白话：</label>
  <div style="position:relative">
    <textarea id="inputBox" placeholder="在这里输入你平时说的话…" style="padding-right:28px"></textarea>
    <button id="btnVoice" title="点击录音" style="position:absolute;right:8px;bottom:10px"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg></button>
  </div>
  <label for="supplementBox">补充（翻译不够时加话，可留空）：</label>
  <textarea id="supplementBox" placeholder="比如：还要能离线用"></textarea>
  <div id="activateBox"><p>免费额度已用完</p><p style="font-size:10px;color:#888" id="activateId"></p><p style="color:#c4a0ff;font-size:11px;margin:8px 0">添加微信 <b>ZMyyPY0710</b> 获取激活码</p><input id="activateCode" placeholder="输入激活码"><button onclick="doActivate()">激活</button><div class="msg" id="activateMsg"></div></div>
  <div class="btn-row">
    <button id="btnTranslate">翻译 →</button>
    <button id="btnCopy" disabled>复制指令</button>
    <span class="status" id="status"></span>
  </div>
  <div class="uncertain" id="uncertainBox"><div class="q" id="uncertainQ"></div><div class="opts" id="uncertainOpts"></div></div>
  <div class="result-label">精准指令（复制后粘贴到任何 AI）：</div>
  <div id="resultBox">翻译结果会显示在这里。</div>
  <div id="backBox" style="display:none;background:#252526;border-radius:6px;padding:8px 10px;margin-top:6px;font-size:12px;color:#a0a0a0;line-height:1.5;white-space:pre-wrap"></div>
</div>
<script>
var lastBody="",lastOriginal="",lastSupplement="";
async function loadProjects(){
  var sel=document.getElementById("projectSelect");sel.innerHTML="";
  try{
    var projects=await window.pywebview.api.get_projects();
    projects.forEach(function(p){var o=document.createElement("option");o.value=p;o.textContent=p;sel.appendChild(o)});
    // 恢复上次选择的项目
    try{var s=await window.pywebview.api.get_saved_project();if(s)sel.value=s;}catch(e){}
  }catch(e){
    var o=document.createElement("option");o.value="默认项目";o.textContent="默认项目";sel.appendChild(o);
    document.getElementById("status").textContent="项目列表读取失败:"+e
  }
}
function waitBridge(fn){
  var n=0;
  var t=setInterval(function(){
    n++;
    if((window.pywebview&&window.pywebview.api)||n>15){clearInterval(t);fn()}
  },300);
}
waitBridge(function(){
  loadProjects();
  setTimeout(function(){
    window.pywebview.api.check_update().then(function(r){
      if(r.ok&&r.latest&&r.url){
        document.getElementById("updateVer").textContent=r.latest;
        document.getElementById("updateLink").setAttribute("data-url",r.url);
        document.getElementById("updateBar").style.display="block";
        document.getElementById("btnUpdate").textContent="新版本";
        document.getElementById("btnUpdate").style.color="#ffd60a";
        document.getElementById("btnUpdate").style.borderColor="#ffd60a";
      }
    }).catch(function(){});
  },500);
});
// 更新按钮手动检查
function checkForUpdate(quiet){
  if(quiet)document.getElementById("btnUpdate").textContent="检查中…";
  window.pywebview.api.check_update().then(function(r){
    if(r.ok&&r.latest){document.getElementById("updateVer").textContent=r.latest;document.getElementById("updateBar").style.display="block";document.getElementById("btnUpdate").textContent="新版本"}
    else{if(quiet)alert("已是最新版本");document.getElementById("btnUpdate").textContent="更新"}
  }).catch(function(){if(quiet)alert("网络不通");document.getElementById("btnUpdate").textContent="更新"})
}
function doUpdate(){
  var u=document.getElementById("updateLink").getAttribute("data-url");
  document.getElementById("updateBar").innerHTML='下载中…完成后自动重启';
  window.pywebview.api.do_update(u).then(function(r){if(!r||!r.ok)document.getElementById("updateBar").innerHTML='失败'}).catch(function(e){document.getElementById("updateBar").innerHTML='出错'+e})
}
document.getElementById("btnUpdate").onclick=function(){checkForUpdate(true)};
document.getElementById("modeSelect").onchange=function(){
  var is=this.value==="project";
  document.getElementById("projectSelect").style.display=is?"inline":"none";
  document.getElementById("btnNewProject").style.display=is?"inline":"none";
  document.getElementById("btnDelProject").style.display=is?"inline":"none"
};
document.getElementById("modeSelect").onchange();
document.getElementById("btnNewProject").onclick=async function(){
  var n=prompt("项目名称：");if(!n)return;
  try{var ok=await window.pywebview.api.create_project(n);if(ok){loadProjects();document.getElementById("projectSelect").value=n}else alert("项目已存在")}catch(e){alert("失败:"+e)}
};
document.getElementById("btnDelProject").onclick=async function(){
  var p=document.getElementById("projectSelect").value||"";
  if(!p||p==="默认项目"){alert("没有可删除的项目");return}
  if(!confirm("确定删除项目「"+p+"」吗？会同时删除它的记忆文件"))return;
  try{
    var ok=await window.pywebview.api.delete_project(p);
    if(ok){alert("已删除");loadProjects();document.getElementById("projectSelect").value="默认项目"}
    else alert("删除失败")
  }catch(e){alert("失败:"+e)}
};
function showUncertain(u,opts){
  var b=document.getElementById("uncertainBox");
  if(u){b.style.display="block";document.getElementById("uncertainQ").textContent=u;
    var d=document.getElementById("uncertainOpts");d.innerHTML="";
    if(opts&&opts.length)opts.forEach(function(o){var x=document.createElement("button");x.className="opt";x.textContent=o;
      x.onclick=function(){
        lastSupplement=document.getElementById("supplementBox").value.trim()+"\n（我选："+o+"）";
        var uq=document.getElementById("uncertainQ").textContent||"";
        var mm=uq.match(/【拿不准[：:](.+?)(是指|指的是)?[？?]】/);
        if(mm&&mm[1]){try{window.pywebview.api.save_reference(document.getElementById("projectSelect").value||"默认项目",mm[1],o)}catch(e){}}
        doTranslate()
      };
      d.appendChild(x)})
  }else b.style.display="none"
}
async function doTranslate(){
  var o=document.getElementById("inputBox").value.trim();
  var s=lastSupplement||document.getElementById("supplementBox").value.trim();
  lastOriginal=o;lastSupplement=s;
  if(!o){document.getElementById("status").textContent="先输入白话";return}
  var btn=document.getElementById("btnTranslate"),st=document.getElementById("status");
  st.textContent="翻译中…";btn.disabled=true;
  try{
    var m=document.getElementById("modeSelect").value;
    var r=await window.pywebview.api.translate(o,s,document.getElementById("projectSelect").value||"默认项目",m);
    if(r.ok){
      var parts=r.body.split(/---\n?/);
      var instruction=parts[0].trim().replace(/^精[准确]指[令示][：:]\s*/,"").replace(/^指[令示][：:]\s*/,"");
      var back=parts.length>1?parts.slice(1).join("---").trim():"";
      document.getElementById("resultBox").textContent=instruction;
      var backBox=document.getElementById("backBox");
      if(back){backBox.style.display="block";backBox.innerHTML='<span style="color:#86868b;font-size:10px">回译对照（通俗版，对比看意思对不对）：</span><br>'+back}
      else backBox.style.display="none";
      lastBody=instruction;
      showUncertain(r.uncertain,r.options);
      document.getElementById("btnCopy").disabled=false;st.textContent="完成 · "+r.tokens+" token";
    }else{st.textContent="失败";var err=r.error||"未知错误";
      document.getElementById("resultBox").textContent=err;
      if(r.need_activate){document.getElementById("activateBox").style.display="block";
        window.pywebview.api.get_install_id_api().then(function(id){document.getElementById("activateId").textContent="你的安装ID: "+id}).catch(function(){})}
    }
  }catch(e){st.textContent="出错";document.getElementById("resultBox").textContent="调用出错，请检查网络"}
  btn.disabled=false
}
document.getElementById("btnTranslate").onclick=doTranslate;
document.getElementById("btnCopy").onclick=async function(){
  if(!lastBody)return;
  var st=document.getElementById("status");
  try{
    var ok=await window.pywebview.api.copy_to_clipboard(lastBody);
    st.textContent=ok?"已复制，去粘贴":"复制失败，请再点一次";
    if(ok)window.pywebview.api.save_to_memory(lastOriginal,document.getElementById("projectSelect").value||"默认项目");
  }catch(e){st.textContent="复制失败："+e}
};
document.getElementById("supplementBox").addEventListener("input",function(){lastSupplement=""});
document.getElementById("btnVoice").onclick=async function(){
  var st=document.getElementById("status"),inp=document.getElementById("inputBox"),b=document.getElementById("btnVoice");
  if(b.dataset.recording==="1"){
    st.textContent="⏹ 停止录音，识别中…";b.dataset.recording="0";b.style.borderColor="#555";
    try{var r=await window.pywebview.api.start_voice();
      if(r.ok){inp.value=(inp.value?inp.value+" ":"")+r.text;st.textContent="✅ 语音完成"}else st.textContent="语音失败: "+(r.error||"请尝试使用系统听写（按两下 Control）")
    }catch(e){st.textContent="语音不可用: "+e}
    setTimeout(function(){st.textContent=""},3000)
  }else{
    st.textContent="🔴 录音中…再点停止";b.dataset.recording="1";b.style.borderColor="#ff3b30";inp.focus();
    try{await window.pywebview.api.start_voice()}catch(e){st.textContent="录音启动失败: "+e;b.dataset.recording="0"}
  }
};
</script></body></html>"""


# ==== 激活函数 (JS) ====
ACTIVATE_JS = """
async function doActivate(){
  var code=document.getElementById('activateCode').value.trim(),m=document.getElementById('activateMsg');
  if(!code){m.textContent='请输入激活码';return}
  m.textContent='验证中...';
  try{var r=await window.pywebview.api.activate(code);
    if(r.ok){m.textContent=r.msg;m.style.color='#a5d6a7';document.getElementById('activateBox').style.display='none';document.getElementById('status').textContent='已激活'}
    else{m.textContent=r.msg;m.style.color='#ff6b6b'}
  }catch(e){m.textContent='验证出错'}
}
"""
# 注入 JS 到 HTML
HTML = HTML.replace("</script>", ACTIVATE_JS + "\n</script>")

def main():
    if not _acquire_single_instance():
        return
    # macOS Dock 行为：关窗口=隐藏，点Dock=恢复，右键=退出
    try:
        from AppKit import NSApplication, NSApp, NSObject, NSApplicationActivationPolicyRegular
        import objc
        
        NSApplication.sharedApplication()
        NSApp().setActivationPolicy_(NSApplicationActivationPolicyRegular)
        
        # AppDelegate 只处理 Dock 点击恢复
        class AppDelegate(NSObject):
            def init(self):
                self = objc.super(AppDelegate, self).init()
                return self
            def applicationShouldHandleReopen_hasVisibleWindows_(self, app, flag):
                """点 Dock 图标 → 重新打开窗口"""
                webview.create_window("说AI懂的话", html=HTML, width=420, height=680,
                    min_size=(360,500), js_api=api, background_color="#1e1e1e")
                webview.start(gui='cocoa')
                return False
            def applicationShouldTerminateAfterLastWindowClosed_(self, app):
                return False  # 关窗口不退出
        
        NSApp().setDelegate_(AppDelegate.alloc().init())
        
        # 先打开第一个窗口，再进入事件循环
        webview.create_window("说AI懂的话", html=HTML, width=420, height=680,
                              min_size=(360,500), js_api=api, background_color="#1e1e1e")
        webview.start(gui='cocoa')
        # 窗口关闭后保持运行，等待 Dock 点击
        NSApp().run()
    except Exception:
        webview.create_window("说AI懂的话", html=HTML, width=420, height=680,
                              min_size=(360,500), js_api=api, background_color="#1e1e1e")
        webview.start()

if __name__ == "__main__": main()
