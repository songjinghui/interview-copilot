#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地面试录音/转写环境基础探测脚本

用途：
- 不下载模型、不处理真实音频，仅检查目标电脑上是否具备常见本地转写方案所需的基础环境。
- 帮助判断下一步是否需要安装 whisper、ffmpeg、pyaudio/sounddevice 等依赖。

运行方式：
    python local_probe.py

输出：
    results/local_probe_report.json
    results/local_probe_report.md
"""

import importlib.util
import json
import os
import platform
import sys
from datetime import datetime, timezone

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def check_ffmpeg() -> bool:
    """检查 ffmpeg 是否在 PATH 中可用。"""
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        exe = os.path.join(path_dir, "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        if os.path.isfile(exe):
            return True
    return False


def list_audio_devices() -> dict:
    """尝试列出音频输入设备；不强制要求安装音频库。"""
    result = {"available": False, "library": None, "devices": [], "error": None}
    if has_module("sounddevice"):
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            inputs = [d for d in devices if d["max_input_channels"] > 0]
            result["available"] = True
            result["library"] = "sounddevice"
            result["devices"] = [
                {"name": d["name"], "channels": d["max_input_channels"], "index": i}
                for i, d in enumerate(inputs)
            ]
        except Exception as e:
            result["error"] = f"sounddevice error: {str(e)[:200]}"
    elif has_module("pyaudio"):
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            result["available"] = True
            result["library"] = "pyaudio"
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    result["devices"].append(
                        {
                            "name": info.get("name"),
                            "channels": info.get("maxInputChannels"),
                            "index": i,
                        }
                    )
            pa.terminate()
        except Exception as e:
            result["error"] = f"pyaudio error: {str(e)[:200]}"
    else:
        result["error"] = "未安装 sounddevice 或 pyaudio，无法枚举音频设备"
    return result


def main():
    result = {
        "meta": {
            "purpose": "本地转写环境基础探测",
            "run_at": now_iso(),
            "disclaimer": "本脚本不下载模型、不处理真实音频，仅检查环境依赖。",
        },
        "environment": {
            "platform": platform.platform(),
            "python_version": sys.version,
            "python_executable": sys.executable,
        },
        "optional_dependencies": {
            "openai-whisper": has_module("whisper"),
            "faster-whisper": has_module("faster_whisper"),
            "torch": has_module("torch"),
            "sounddevice": has_module("sounddevice"),
            "pyaudio": has_module("pyaudio"),
            "ffmpeg_in_path": check_ffmpeg(),
        },
        "audio_input_devices": list_audio_devices(),
    }

    # JSON 报告
    json_path = os.path.join(RESULTS_DIR, "local_probe_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Markdown 报告
    md_path = os.path.join(RESULTS_DIR, "local_probe_report.md")
    deps = result["optional_dependencies"]
    audio = result["audio_input_devices"]
    lines = [
        "# 本地转写环境基础探测报告",
        "",
        f"- 探测时间：{result['meta']['run_at']}",
        f"- 说明：{result['meta']['disclaimer']}",
        "",
        "## 运行环境",
        "",
        f"- 平台：{result['environment']['platform']}",
        f"- Python：{result['environment']['python_version'].split()[0]}",
        f"- 解释器：{result['environment']['python_executable']}",
        "",
        "## 可选依赖",
        "",
        "| 依赖 | 状态 |",
        "|------|------|",
        f"| openai-whisper | {'已安装' if deps['openai-whisper'] else '未安装'} |",
        f"| faster-whisper | {'已安装' if deps['faster-whisper'] else '未安装'} |",
        f"| torch | {'已安装' if deps['torch'] else '未安装'} |",
        f"| sounddevice | {'已安装' if deps['sounddevice'] else '未安装'} |",
        f"| pyaudio | {'已安装' if deps['pyaudio'] else '未安装'} |",
        f"| ffmpeg (PATH) | {'可用' if deps['ffmpeg_in_path'] else '未找到'} |",
        "",
        "## 音频输入设备",
        "",
    ]
    if audio["available"]:
        lines.append(f"检测到库：{audio['library']}")
        if audio["devices"]:
            lines.append("| 设备 | 通道数 | 索引 |")
            lines.append("|------|--------|------|")
            for d in audio["devices"]:
                lines.append(f"| {d['name']} | {d['channels']} | {d['index']} |")
        else:
            lines.append("未找到音频输入设备。")
    else:
        lines.append(f"无法枚举音频设备：{audio['error']}")

    lines += [
        "",
        "## 说明",
        "",
        "1. **本探测不下载模型**：whisper 等模型文件较大，首次下载可能需要数分钟到数十分钟，建议在确定选型后手动完成。",
        "2. **不验证转写准确率**：准确率、处理速度、资源占用、术语识别和多人说话人分离需要在实际面试录音样本上测试。",
        "3. **录音场景多样**：浏览器标签页、腾讯会议/钉钉/飞书等桌面客户端、线下面试的采集方式各不相同，需分别验证。",
        "",
        "## 下一步建议",
        "",
        "- 在目标电脑上安装候选转写库（如 `pip install openai-whisper` 或 `pip install faster-whisper`）并下载模型。",
        "- 用一段真实面试录音或模拟双人对话测试转写准确率、时间戳对齐和说话人区分。",
        "- 在断网环境下验证本地模型能否正常运行。",
        "- 测量长录音（30 分钟以上）的处理时间、内存和磁盘占用。",
    ]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"本地探测报告已保存：")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")


if __name__ == "__main__":
    main()
