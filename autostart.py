# -*- coding: utf-8 -*-
"""开机自启：写 HKCU Run 项"""
import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "WatermarkLyric"


def _command():
    if getattr(sys, "frozen", False):      # 打包成 exe：直接指向自己
        return f'"{sys.executable}"'
    exe = sys.executable
    low = exe.lower()
    if low.endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
    return f'"{exe}" "{script}"'


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, NAME)
            return bool(value)
    except OSError:
        return False


def set_enabled(on):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(k, NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
