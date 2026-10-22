# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

红外摄像头桌面播放器，技术栈：Python + PySide6/Qt + OpenCV。支持普通摄像头和红外摄像头两种模式。红外模式下从 UVC YUV422 原始帧重建 14-bit 温度数据，经过直方图均衡、中值滤波、伪彩映射后显示。

## 构建与运行

```bash
# 安装依赖
pip install -r python/requirements.txt

# 运行应用（开发模式）
python python/infrared_camera_player.py

# 运行测试
python -m pytest python/tests/ -v
# 或
python -m unittest python/tests/test_infrared_pipeline.py -v

# 打包成 EXE（在仓库根目录执行）
powershell -File python/build_exe.ps1
# EXE 输出到 dist/InfraredCameraPlayer.exe
```

PyInstaller 打包使用 `python/infrared_camera_player.spec`，onefile 模式，console=False。

## 架构

核心模块在 `python/infrared_player/`：

| 模块 | 职责 |
|------|------|
| `models.py` | 数据结构：`CameraDevice`、`CameraKind`（Normal/Infrared 枚举）、`InfraredFrame`（temp14/gray8/pseudo_rgb）、`DisplayState` |
| `camera_enumerator.py` | 枚举摄像头：OpenCV 探测可用索引 + PowerShell 查询 Windows 设备真实名称，按位置配对 |
| `capture_controller.py` | 管理 `cv2.VideoCapture` 生命周期（打开/释放/切换）。红外模式设置 `CAP_PROP_CONVERT_RGB=0`、分辨率 520×202、YUY2 格式 |
| `frame_router.py` | 根据 `CameraKind` 分发帧：普通模式 BGR→RGB 转换，红外模式走 `InfraredProcessor` |
| `infrared.py` | 红外处理流水线，见下文 |
| `ui.py` | `MainWindow`（QMainWindow），30ms 定时器轮询帧，根据摄像头类型和显示开关状态更新画面 |
| `app.py` | 入口，创建 QApplication 和 MainWindow |

**数据流：** `CaptureController.read()` → `FrameRouter.route()` → `InfraredProcessor.process()` → `MainWindow._set_image()` 显示到 QLabel

## 红外处理流水线

红外帧尺寸：UVC 逻辑宽度 520×202，重建后有效像素 260×202（不丢弃最后一行）。

处理步骤（`infrared.py`）：
1. **`decode_infrared_payload()`**：每像素 4 字节，取每个字节高 4 位拼成 16-bit 值（`(b0_hi<<12)|(b1_hi<<8)|(b2_hi<<4)|b3_hi`），取低 14 位 → `temp14`
2. **`histogram_equalize_temperature()`** — 不做 clip，直接在 temp14 全范围上做直方图均衡，输出 8-bit 灰度图
3. **`median_filter()`**：默认 3×3 核，偶数核自动 +1，使用 `cv2.medianBlur`（无 OpenCV 时有纯 NumPy fallback）
4. **`gray_to_pseudo()`**：四段分段线性伪彩映射（蓝→青→绿→红→白）

**重要常量和参数：**
- `IR_WIDTH = 260`, `IR_HEIGHT = 202`, `RAW_IR_HEIGHT = 202`
- `IR_UVC_WIDTH = 520`（260×2 字节）
- `DEFAULT_MEDIAN_KERNEL = 3`
- 裁剪比例和温度上下限已被直方图均衡替代（见 git log）

## C++ 项目（Legacy）

`OpenCamera/` 目录包含一个简单的 Visual Studio 2022 C++ 控制台项目，使用 OpenCV 4.8.0（opencv_world480.lib）打开摄像头并显示画面。这是一个早期测试项目，不需要维护。

## 老脚本

`python/` 下 `ir14_clip.py`、`ir14_eq.py`、`ir14_to_bmp.py`、`high4_combine.py` 是红外处理流水线的早期原型脚本，从 `.bin` 文件读取而非实时采集。可作为算法参考但不参与打包。
