# OpenCamera_c — 红外摄像头播放器（Python UI + C 模型计算）

第三个工程，结合前两个工程：

- **OpenCamera**（`python/`）：红外摄像头 UI、数据抓取、校准、显示。
- **c_model**（`c_model/`）：芯片设计的 C 语言参考模型。

本项目复用 OpenCamera 的 UI / 抓取 / 校准 / 显示，把「中间计算」替换为
c_model 的 C 模块，用于**在真实摄像头数据上实时动态验证 C 模型**。

## 架构

```
CaptureController.read()  (520×202×2 原始 UVC 字节流)
        │
        ▼
InfraredProcessor (python/infrared_player/infrared.py)
        │  经 ctypes 调用 c_model_bridge.dll
        ▼
C 流水线（引用 ../c_model 源码，单一真源）：
  sampling(采样) → 校准(可选) → filter(滤波：高斯/中值) → clip(极值截取：平均/低通)
  → compress(线性压缩 14→10bit) → hist_eq(直方图均衡 10→8bit) → color(查表伪彩)
        │
        ▼
InfraredFrame(temp14, gray8, pseudo_rgb, clip_min, clip_max) → 显示
```

关键差异（相对 OpenCamera，属预期行为变化）：

| 项目 | OpenCamera | OpenCamera_c |
|------|-----------|--------------|
| 滤波 | 双边滤波 | 3×3 高斯 / 中值（UI 可切换） |
| 灰度 | 直方图均衡(14bit) + 中值 + 反相 | clip+compress(14→10bit)+hist_eq(10→8bit) |
| 伪彩 | numpy LUT | c_model 内置 LUT（蓝→青→绿→红→白，高温=白） |
| 尺寸 | 260×201（丢最后一行） | 260×202（不丢） |

## 目录结构

```
OpenCamera_c/
├── c_bridge/
│   ├── bridge.h / bridge.c      # 有状态流水线封装（include ../c_model/config.h）
│   ├── build_dll.ps1            # 编译 ../c_model/*.c + bridge.c → c_model_bridge.dll
│   └── c_model_bridge.dll       # 构建产物（gitignore）
└── python/
    ├── infrared_camera_player.py / infrared_camera_player.spec / build_exe.ps1
    ├── infrared_player/
    │   ├── c_bridge.py          # ctypes 封装（加载 DLL + CBridge）
    │   ├── infrared.py          # C 驱动的 InfraredProcessor
    │   ├── ui.py / models.py / frame_router.py / capture_controller.py /
    │   │   camera_enumerator.py / app.py   # 复用 OpenCamera（少量调整）
    └── tests/test_c_bridge.py   # C vs numpy 参考实现的离线验证
```

## 构建与运行

```bash
# 1. 编译 C 桥接 DLL（引用仓库根 ../c_model 源码）
powershell -File OpenCamera_c/c_bridge/build_dll.ps1

# 2. 离线验证（无需摄像头，用 data/1.bin 比对 C 输出与 numpy 参考实现）
python -m unittest discover -s OpenCamera_c/python/tests -v

# 3. 运行应用（需红外摄像头）
python OpenCamera_c/python/infrared_camera_player.py

# 4. 打包 EXE（onefile，含 DLL）
powershell -File OpenCamera_c/python/build_exe.ps1
```

动态验证流程：修改 `c_model/` 下任意模块 → 重跑 `build_dll.ps1` → 重启应用即可
验证新算法在真实数据上的表现。底部状态栏实时显示 C 侧极值截取的
`[min, max]`，用于观察 clip 模块多帧平滑的收敛过程。红外模式下工具栏提供
「滤波」「极值计算」「灰度反相」三个控件，可实时切换滤波方式（高斯/中值）、
极值计算方式（平均/低通）与灰度是否反相。

## C 桥接层 API（ctypes 可见）

| 函数 | 说明 |
|------|------|
| `bridge_init()` | 默认配置 + 复位极值状态 |
| `bridge_set_clip_user(mn, mx)` / `bridge_set_clip_dynamic(n, step)` | 极值截取配置 |
| `bridge_set_filter_mode(mode)` | 滤波方式 0=高斯 / 1=中值 |
| `bridge_set_clip_calc_mode(mode)` | 极值计算方式 0=滑动窗口平均 / 1=低通 |
| `bridge_set_hist_reverse(reverse)` | 灰度反相 0=升序 / 1=反相 |
| `bridge_set_lut(r, g, b)` | 自定义伪彩 LUT（NULL 恢复内置） |
| `bridge_decode(stream, n, out)` | 模块 1 采样：字节流 → 14-bit 紧凑图 |
| `bridge_process(stream, n, calib, temp14, gray8, rgb, min, max)` | 完整流水线 |

`calib` 为 `NULL` 或 202×260 个 `int16` 校准误差图（由 Python 校准步骤计算，
在采样之后、高斯之前逐像素相减并 clamp 到 `[0, 0x3FFF]`）。

## 说明

- c_model 源码以「引用编译」方式接入（单一真源）：`bridge.c` 直接 `#include
  ../c_model/config.h` 复用模块函数。若 c_model 的 `config.h` 或模块签名变更，
  需同步 `bridge.c` 后重编译。
- 校准误差图量化为 `int16`（均值取整），与 OpenCamera 的 float 版本有 <1 LSB
  差异，可忽略。
