#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PromptBridge Float v1.0
浮窗版：快捷键唤出 → 自动翻译选中文字 → 确认替换
macOS: 无边框置顶浮窗，Win+Shift+T 触发
"""
import webview, json, urllib.request, os, re, subprocess, platform, threading, socket, shutil, sys, time
from license import check_and_count as _check_license, get_install_id as _install_id, activate as _activate
from reporter import report_usage as _report

MODEL = "deepseek-v4-flash"
API_URL = "https://sayai-dashboard.onrender.com/translate"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(os.path.expanduser("~/Library/Application Support/说AI懂的话/记忆本"))
os.makedirs(MEMORY_DIR, exist_ok=True)

IS_MAC = platform.system() == "Darwin"

try:
    from opencc import OpenCC as _OpenCC
    _cc = _OpenCC("t2s")
    def to_simplified(text):
        try: return _cc.convert(text)
        except Exception: return text
except Exception:
    def to_simplified(text): return text

# ---- 捕获前方 App ----
def _get_frontmost_app():
    try:
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of first application process whose frontmost is true'],
            capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return ""

# ---- 获取屏幕尺寸 ----
def _get_screen_size():
    try:
        r = subprocess.run(["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=5)
        m = re.search(r'Resolution: (\d+) x (\d+)', r.stdout)
        if m: return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 1920, 1080

_lock_socket = None

def _acquire_single_instance():
    global _lock_socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 47838))
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
（注意：这一行必须单独成行，不能写进精准指令正文；没有歧义就绝对不要输出）"""

def call_deepseek(messages, max_tokens=900):
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
            all_options_text = uncertain
            for j in range(i+1, min(i+6, len(lines))):
                ol = lines[j].strip()
                if re.match(r'^[A-C][.．、]', ol):
                    options.append(re.sub(r'^[A-C][.．、]\s*', '', ol).strip().rstrip("。"))
                    all_options_text += "\n" + ol
                elif ol == '' and not options: continue
                elif options: break
            if not options:
                m = re.search(r'[？?]\s*[—\-]\s*(.*)', uncertain)
                if not m: m = re.search(r'选项[：:]\s*(.*)', uncertain)
                if m:
                    part = m.group(1)
                    parts = re.split(r'\s*[A-C][.．、]\s*', part)
                    options = [p.strip().rstrip("。").rstrip("？") for p in parts[1:] if p.strip()][:3]
            if not options:
                parts = re.split(r'[A-C][.．、]\s*', uncertain)
                options = [p.strip().rstrip("。").rstrip("？") for p in parts[1:] if p.strip()][:3]
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

def _read_last_project():
    """读取上次使用的项目名"""
    try:
        p = os.path.join(MEMORY_DIR, ".last_project")
        if os.path.exists(p):
            with open(p) as f: return f.read().strip()
    except Exception: pass
    return "默认项目"

def _save_last_project(name):
    try:
        with open(os.path.join(MEMORY_DIR, ".last_project"), "w") as f:
            f.write(name)
    except Exception: pass

class Api:
    def __init__(self, prev_app=""):
        self.prev_app = prev_app
        self.current_project = _read_last_project()
        self.current_memory = load_memory(self.current_project)

    def translate(self, original, supplement, project_name, mode):
        ok, rem, msg = _check_license()
        if not ok:
            return {"ok": False, "error": msg, "need_activate": True}
        combined = original
        if supplement.strip():
            combined = f"{original}\n\n补充：{supplement.strip()}"
        mem_hint = ""
        if mode == "project":
            if project_name != self.current_project:
                self.current_project = project_name
                self.current_memory = load_memory(project_name)
                _save_last_project(project_name)
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
            try:
                threading.Thread(target=_report,
                    args=(_install_id, tokens), daemon=True).start()
            except Exception: pass
            return {"ok": True, "body": body, "uncertain": uncertain, "options": options, "tokens": tokens}
        except Exception as e:
            return {"ok": False, "error": str(e)}

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
            save_memory(project_name, mem)
            _save_last_project(project_name)
            return True
        except Exception: return False

    def apply_option(self, original, supplement, option, project_name, mode):
        return self.translate(original, supplement.strip() + "\n（我选：" + option + "）", project_name, mode)

    def save_to_memory(self, text, project_name):
        try:
            mem = load_memory(project_name)
            mem.setdefault("最近使用", []).insert(0, text[:60])
            mem["最近使用"] = mem["最近使用"][:20]
            save_memory(project_name, mem)
            _save_last_project(project_name)
        except Exception: pass

    def get_projects(self): return list_projects()

    def create_project(self, name):
        p = os.path.join(MEMORY_DIR, f"{name}.json")
        if os.path.exists(p): return False
        save_memory(name, {"指代": {}, "纠错": {}, "最近使用": []})
        return True

    def delete_project(self, name):
        try:
            if not name or name == "默认项目": return False
            p = os.path.join(MEMORY_DIR, f"{name}.json")
            if os.path.exists(p): os.remove(p)
            if self.current_project == name:
                self.current_project = "默认项目"
                self.current_memory = load_memory("默认项目")
                _save_last_project("默认项目")
            return True
        except Exception:
            return False

    def save_reference(self, project_name, word, choice):
        try:
            mem = load_memory(project_name) if project_name != self.current_project else self.current_memory
            mem.setdefault("指代", {})[word.strip()] = choice.strip()
            save_memory(project_name, mem)
            return True
        except Exception:
            return False

    def paste_and_close(self, text):
        """复制到剪贴板 → 切回前方App → Cmd+V → 退出"""
        try:
            subprocess.run(["/usr/bin/pbcopy"], input=text.encode("utf-8"), timeout=5)
        except Exception:
            pass
        try:
            if self.prev_app and self.prev_app not in ("", "说AI懂的话", "Hermes"):
                escaped = self.prev_app.replace('"', '\\"')
                subprocess.run([
                    "osascript", "-e",
                    f'tell application "{escaped}" to activate',
                    "-e",
                    'tell application "System Events" to keystroke "v" using command down'
                ], timeout=5)
        except Exception:
            pass
        # 结束进程
        os._exit(0)


# ============================================================
# 浮窗 HTML（紧凑、无边框、深色）
# ============================================================
HTML = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
body{background:#1e1e1e;color:#e8e8e8;overflow:hidden;user-select:none}
.drag-bar{height:28px;background:#252526;display:flex;align-items:center;padding:0 10px;cursor:move}
.drag-bar .title{font-size:12px;font-weight:600}
.drag-bar .proj-area{margin-left:auto;display:flex;align-items:center;gap:6px;cursor:default}
.drag-bar select{background:#3a3a3c;color:#e8e8e8;border:1px solid #555;border-radius:4px;padding:2px 6px;font-size:10px}
.drag-bar button{background:#3a3a3c;color:#e8e8e8;border:1px solid #555;border-radius:4px;padding:2px 6px;font-size:9px;cursor:pointer}
.content{padding:10px 14px;display:flex;flex-direction:column;gap:8px}
.status-line{font-size:10px;color:#9d9d9d;min-height:16px}
#resultBox{background:#2d2d30;border:1px solid #3a3a3c;border-radius:6px;padding:10px;font-size:13px;line-height:1.6;white-space:pre-wrap;min-height:60px;max-height:200px;overflow-y:auto}
#backBox{display:none;background:#252526;border-radius:6px;padding:8px 10px;font-size:11px;color:#a0a0a0;line-height:1.5;white-space:pre-wrap;max-height:100px;overflow-y:auto}
.uncertain{display:none;background:#3a2e00;border-radius:6px;padding:8px 10px}
.uncertain .q{color:#ffd60a;font-size:11px;margin-bottom:5px}
.uncertain .opts{display:flex;gap:6px;flex-wrap:wrap}
.uncertain .opt{background:#4a3d00;color:#ffd60a;border:none;padding:4px 10px;border-radius:4px;font-size:11px;cursor:pointer}
.uncertain .opt:hover{background:#5a4d00}
#activateBox{display:none;background:#2d1b4e;border-radius:8px;padding:12px;text-align:center}
#activateBox p{color:#c4a0ff;font-size:11px;margin-bottom:8px}
#activateBox input{background:#3a3a3c;color:#e8e8e8;border:1px solid #7c5ce7;border-radius:4px;padding:6px 10px;font-size:12px;width:200px;text-align:center}
#activateBox button{background:#7c5ce7;color:#fff;padding:6px 14px;border-radius:4px;font-size:11px;margin-left:6px}
#activateBox .msg{color:#ff6b6b;font-size:10px;margin-top:6px}
.btn-row{display:flex;gap:8px;justify-content:center}
#btnReplace{background:#30d158;color:#fff;border:none;padding:8px 24px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer}
#btnReplace:hover{background:#53d769}
#btnReplace:disabled{background:#3a3a3c;color:#777;cursor:not-allowed}
#btnCancel{background:#3a3a3c;color:#e8e8e8;border:1px solid #555;padding:8px 24px;border-radius:6px;font-size:13px;cursor:pointer}
#btnCancel:hover{background:#555}
/* 自定义弹窗遮罩 */
.dialog-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:100;align-items:center;justify-content:center}
.dialog-overlay.show{display:flex}
.dialog-card{background:#2d2d30;border-radius:10px;padding:20px;min-width:280px;max-width:400px}
.dialog-card h3{color:#e8e8e8;font-size:13px;margin-bottom:12px}
.dialog-card input{width:100%;background:#3a3a3c;color:#e8e8e8;border:1px solid #555;border-radius:6px;padding:8px;font-size:13px;margin-bottom:12px;outline:none}
.dialog-card input:focus{border-color:#0a84ff}
.dialog-card .dialog-btns{display:flex;gap:8px;justify-content:flex-end}
.dialog-card .dialog-btns button{padding:6px 16px;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer}
.dialog-card .btn-ok{background:#0a84ff;color:#fff}
.dialog-card .btn-cancel{background:#3a3a3c;color:#e8e8e8}
</style></head><body>

<div class="drag-bar">
  <span class="title">说AI懂的话</span>
  <div class="proj-area">
    <select id="projectSelect"></select>
    <button id="btnNewProject" title="新建项目">+</button>
    <button id="btnDelProject" title="删除项目">✕</button>
  </div>
</div>

<div class="content">
  <div class="status-line" id="status">翻译中…</div>
  <div id="resultBox"></div>
  <div class="uncertain" id="uncertainBox">
    <div class="q" id="uncertainQ"></div>
    <div class="opts" id="uncertainOpts"></div>
  </div>
  <div id="backBox"></div>
  <div id="activateBox">
    <p>免费额度已用完</p>
    <p style="font-size:10px;color:#888" id="activateId"></p>
    <input id="activateCode" placeholder="输入激活码">
    <button onclick="doActivate()">激活</button>
    <div class="msg" id="activateMsg"></div>
  </div>
  <div class="btn-row">
    <button id="btnCancel">取消 ✕</button>
    <button id="btnReplace" disabled>确认替换 ↓</button>
  </div>
</div>

<!-- 自定义弹窗 -->
<div class="dialog-overlay" id="dlgOverlay">
  <div class="dialog-card">
    <h3 id="dlgTitle">提示</h3>
    <p id="dlgMsg" style="color:#e8e8e8;font-size:12px;margin-bottom:12px;line-height:1.5;display:none"></p>
    <input id="dlgInput" style="display:none">
    <div class="dialog-btns">
      <button class="btn-cancel" id="dlgCancel">取消</button>
      <button class="btn-ok" id="dlgOk">确定</button>
    </div>
  </div>
</div>

<script>
var lastBody="",lastOriginal="",lastSupplement="",lastOptions=[],lastUncertain="",inputText="INPUT_TEXT_PLACEHOLDER",currentMode="project";

function _alert(m,cb){showDlg("提示",m,false,cb)}
function _confirm(m,cb){showDlg("确认",m,false,cb)}
function _prompt(m,cb){showDlg("输入",m,true,cb)}

function showDlg(title,msg,hasInput,cb){
  var ol=document.getElementById("dlgOverlay");
  document.getElementById("dlgTitle").textContent=title;
  var mi=document.getElementById("dlgInput"),mm=document.getElementById("dlgMsg");
  if(hasInput){mi.style.display="block";mi.value="";mm.style.display="none"}
  else{mi.style.display="none";mm.style.display="block";mm.textContent=msg}
  ol.classList.add("show");
  var done=false;
  function cleanup(){ol.classList.remove("show");done=true}
  document.getElementById("dlgOk").onclick=function(){cleanup();if(cb)cb(hasInput?mi.value.trim():true)};
  document.getElementById("dlgCancel").onclick=function(){cleanup();if(cb)cb(hasInput?null:false)}
}

function loadProjects(){
  var sel=document.getElementById("projectSelect");sel.innerHTML="";
  try{
    var projects=DEFAULT_PROJECTS_JSON;
    if(projects.length===0){var o=document.createElement("option");o.value="默认项目";o.textContent="默认项目";sel.appendChild(o)}
    else projects.forEach(function(p){var o=document.createElement("option");o.value=p;o.textContent=p;sel.appendChild(o)});
  }catch(e){
    var o=document.createElement("option");o.value="默认项目";o.textContent="默认项目";sel.appendChild(o)
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
  // 填充当前项目
  setTimeout(function(){
    var sel=document.getElementById("projectSelect");
    if("CURRENT_PROJECT_PLACEHOLDER"){sel.value="CURRENT_PROJECT_PLACEHOLDER"}
    // 自动翻译
    if(inputText){
      doTranslate(inputText, currentMode);
    }
  },200);
});

function showUncertain(u,opts){
  lastOptions=opts||[];lastUncertain=u||"";
  var b=document.getElementById("uncertainBox");
  if(u){b.style.display="block";document.getElementById("uncertainQ").textContent=u;
    var d=document.getElementById("uncertainOpts");d.innerHTML="";
    if(opts&&opts.length)opts.forEach(function(o){var x=document.createElement("button");x.className="opt";x.textContent=o;
      x.onclick=function(){
        lastSupplement="（我选："+o+"）";
        var uq=document.getElementById("uncertainQ").textContent||"";
        var mm=uq.match(/【拿不准[：:](.+?)(是指|指的是)?[？?]】/);
        var proj=document.getElementById("projectSelect").value||"默认项目";
        if(mm&&mm[1]){try{window.pywebview.api.save_reference(proj,mm[1],o)}catch(e){}}
        doTranslate(inputText, currentMode)
      };
      d.appendChild(x)})
  }else b.style.display="none"
}

async function doTranslate(text, mode){
  var st=document.getElementById("status"),btn=document.getElementById("btnReplace");
  st.textContent="翻译中…";btn.disabled=true;
  try{
    var proj=document.getElementById("projectSelect").value||"默认项目";
    var r=await window.pywebview.api.translate(text,"",proj,mode);
    if(r.ok){
      var parts=r.body.split(/---\n?/);
      var instruction=parts[0].trim().replace(/^精[准确]指[令示][：:]\s*/,"").replace(/^指[令示][：:]\s*/,"");
      var back=parts.length>1?parts.slice(1).join("---").trim():"";
      document.getElementById("resultBox").textContent=instruction;
      var backBox=document.getElementById("backBox");
      if(back){backBox.style.display="block";
        backBox.innerHTML='<span style="color:#86868b;font-size:10px">回译对照（通俗版，对比看意思对不对）：</span><br>'+back}
      else backBox.style.display="none";
      lastBody=instruction;
      lastOriginal=text;
      showUncertain(r.uncertain,r.options);
      btn.disabled=false;st.textContent="完成 · "+r.tokens+" token";
    }else{st.textContent="失败";
      document.getElementById("resultBox").textContent=r.error||"未知错误";
      if(r.need_activate){document.getElementById("activateBox").style.display="block";
        window.pywebview.api.get_install_id_api().then(function(id){document.getElementById("activateId").textContent="你的安装ID: "+id}).catch(function(){})}
    }
  }catch(e){st.textContent="网络出错";document.getElementById("resultBox").textContent="连接失败，请检查网络后重试"}
}

// 确认替换
document.getElementById("btnReplace").onclick=async function(){
  if(!lastBody)return;
  try{
    var proj=document.getElementById("projectSelect").value||"默认项目";
    window.pywebview.api.save_action(proj,lastOriginal,lastBody);
    await window.pywebview.api.paste_and_close(lastBody);
  }catch(e){}
};

// 取消
document.getElementById("btnCancel").onclick=function(){
  try{window.close()}catch(e){}
};

// 项目下拉切换
document.getElementById("projectSelect").onchange=function(){
  if(inputText){doTranslate(inputText,currentMode)}
};

// 新建项目
document.getElementById("btnNewProject").onclick=function(){
  _prompt("请输入项目名称：",function(n){
    if(!n)return;
    window.pywebview.api.create_project(n).then(function(ok){
      if(ok){loadProjects();document.getElementById("projectSelect").value=n}
      else _alert("项目已存在")
    }).catch(function(e){_alert("失败:"+e)})
  })
};

// 删除项目
document.getElementById("btnDelProject").onclick=function(){
  var p=document.getElementById("projectSelect").value||"";
  if(!p||p==="默认项目"){_alert("没有可删除的项目");return}
  _confirm("确定删除项目「"+p+"」吗？会同时删除它的记忆文件",function(ok){
    if(!ok)return;
    window.pywebview.api.delete_project(p).then(function(rok){
      if(rok){loadProjects();document.getElementById("projectSelect").value="默认项目"}
      else _alert("删除失败")
    }).catch(function(e){_alert("失败:"+e)})
  })
};

// Esc 关闭
document.addEventListener("keydown",function(e){if(e.key==="Escape"){try{window.close()}catch(ex){}}});
</script></body></html>"""

# 授权 JS（从原版复制）
ACTIVATE_JS = r"""
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

HTML = HTML.replace("</script>", ACTIVATE_JS + "\n</script>")


def main():
    import sys as _sys
    _sys.stderr.write(f"FLOAT_START: args={sys.argv[1:]}\n")
    _sys.stderr.flush()
    text = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ""
    _sys.stderr.write(f"FLOAT: text='{text[:50]}...'\n"); _sys.stderr.flush()
    prev_app = _get_frontmost_app()
    _sys.stderr.write(f"FLOAT: prev_app='{prev_app}'\n"); _sys.stderr.flush()
    projects = list_projects()
    _sys.stderr.write(f"FLOAT: projects={projects}\n"); _sys.stderr.flush()
    current_project = _read_last_project()
    _sys.stderr.write(f"FLOAT: current_project='{current_project}'\n"); _sys.stderr.flush()
    if current_project not in projects:
        current_project = "默认项目" if "默认项目" in projects else projects[0] if projects else "默认项目"
    _sys.stderr.write(f"FLOAT: final_project='{current_project}'\n"); _sys.stderr.flush()

    # 注入 Python 数据到 HTML
    import json as _json
    h = HTML
    h = h.replace("INPUT_TEXT_PLACEHOLDER", text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$"))
    h = h.replace("DEFAULT_PROJECTS_JSON", _json.dumps(projects))
    h = h.replace("CURRENT_PROJECT_PLACEHOLDER", current_project)

    # 计算居中位置
    sw, sh = _get_screen_size()
    _sys.stderr.write(f"FLOAT: screen={sw}x{sh}\n"); _sys.stderr.flush()
    win_w, win_h = 520, 380
    x = max(0, (sw - win_w) // 2)
    y = max(0, (sh - win_h) // 2)

    _sys.stderr.write(f"FLOAT: creating window at {x},{y} {win_w}x{win_h}\n"); _sys.stderr.flush()
    api = Api(prev_app=prev_app)
    window = webview.create_window(
        "说AI懂的话", html=h, width=win_w, height=win_h,
        x=x, y=y,
        on_top=True,
        js_api=api, background_color="#1e1e1e"
    )
    _sys.stderr.write(f"FLOAT: window created, starting webview...\n"); _sys.stderr.flush()
    webview.start()
    _sys.stderr.write(f"FLOAT: webview.start() returned\n"); _sys.stderr.flush()


if __name__ == "__main__":
    main()
