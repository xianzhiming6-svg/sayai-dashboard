#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
说AI懂的话 - 用量上报模块
每次翻译后后台静默上报到监控后端
"""
import json, urllib.request, time, threading

# ---- 后端地址（部署后改为你的真实地址）----
BACKEND_URL = "https://sayai-dashboard.onrender.com"  # 部署后替换

def report_usage(install_id, tokens):
    """上报一次翻译用量"""
    if "xxxx" in BACKEND_URL:
        return  # 未配置时静默跳过
    try:
        data = json.dumps({
            "install_id": install_id,
            "tokens": tokens,
            "cost_yuan": round(tokens / 1000000 * 1, 6),
        }).encode()
        req = urllib.request.Request(f"{BACKEND_URL}/report", data=data,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # 上报失败不影响主功能
