#!/bin/bash
cd "$(dirname "$0")"
clear
echo "========================================"
echo "   说AI懂的话 · 激活码生成器"
echo "========================================"
echo ""
echo "请输入朋友的安装ID，然后按回车："
read -p "安装ID: " uid
echo ""
if [ -z "$uid" ]; then
    echo "❌ 没有输入安装ID"
    read -p "按任意键关闭..." 
    exit
fi
code=$(python3 -c "import sys; sys.path.insert(0,'.'); from license import generate_activation; print(generate_activation('$uid'))")
echo "========================================"
echo "  激活码：$code"
echo "========================================"
echo ""
echo "把这个激活码发给朋友就行。"
echo ""
read -p "按任意键关闭..."