#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
说AI懂的话 — 授权与计费模块
- 每个安装免费 50 次翻译
- 次数用完后需付费激活
- 作者可远程更换 API Key 让旧版失效
"""
import os, json, hashlib, time

USAGE_FILE = os.path.join(os.path.expanduser("~/.sayai_usage.json"))

# ---------- 本地次数 ----------
def load_usage():
    try:
        with open(USAGE_FILE) as f: return json.load(f)
    except Exception: return {"count": 0, "activated": False, "install_id": ""}

def save_usage(data):
    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
    with open(USAGE_FILE, "w") as f: json.dump(data, f)

def get_install_id():
    """基于机器指纹生成唯一安装 ID（不可逆）"""
    import platform, uuid
    raw = platform.node() + str(uuid.getnode()) + platform.machine()
    return hashlib.sha256(raw.encode()).hexdigest()[:12]

FREE_LIMIT = 50
_AUTHOR_IDS = ["02fc4dab3d8f"]  # 作者机器免限

def check_and_count():
    """检查是否可用，是则次数+1，返回 (可用, 剩余次数, 消息)"""
    u = load_usage()
    if not u.get("install_id"):
        u["install_id"] = get_install_id()
    # 作者机器豁免
    if u["install_id"] in _AUTHOR_IDS:
        return True, -1, ""
    if u.get("activated"):
        u["count"] = u.get("count", 0) + 1
        save_usage(u)
        return True, -1, "已激活，无限制"
    if u["count"] < FREE_LIMIT:
        u["count"] += 1
        save_usage(u)
        return True, FREE_LIMIT - u["count"], f"免费额度剩余 {FREE_LIMIT - u['count']} 次"
    return False, 0, "免费额度已用完，请联系作者获取激活码"

def activate(code):
    """用激活码激活"""
    # 简单验证：激活码 = SHA256(install_id + 作者密钥) 前 16 位
    SECRET = "sayai_2026_secret_key_xzm"  # 不要泄露
    u = load_usage()
    expected = hashlib.sha256((u.get("install_id", get_install_id()) + SECRET).encode()).hexdigest()[:16]
    if code == expected:
        u["activated"] = True
        save_usage(u)
        return True, "激活成功！"
    return False, "激活码无效"

def generate_activation(install_id):
    """作者专用：根据用户 install_id 生成激活码"""
    SECRET = "sayai_2026_secret_key_xzm"
    return hashlib.sha256((install_id + SECRET).encode()).hexdigest()[:16]

# 命令行：作者生成激活码
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        code = generate_activation(sys.argv[1])
        print("=" * 40)
        print(f"  安装ID: {sys.argv[1]}")
        print(f"  激活码: {code}")
        print("=" * 40)
        print("\n把这个激活码发给朋友就行。")
    else:
        u = load_usage()
        print(f"你的安装ID: {u.get('install_id', get_install_id())}")
        print(f"剩余次数: {FREE_LIMIT - u['count']}")
        print("\n生成激活码: python3 license.py <朋友的安装ID>")
