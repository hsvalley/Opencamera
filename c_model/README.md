# 红外图像处理流水线 C 模型

用于芯片设计的 C 语言参考模型，实现红外图像处理流水线。算法全部手写，
使用定点整数与静态数组（不 malloc、不用 math.h 浮点），仅依赖标准库的
`stdint.h`（固定宽度类型）与 `stdio.h`（文件 I/O）。

## 目录结构

| 文件 | 职责 |
|------|------|
| `config.h` | 类型、常量、各模块配置结构体与函数声明 |
| `config.c` | 默认配置初始化 |
| `sampling.c` | 模块 1：接口温度值采样 |
| `gaussian.c` | 模块 2：3x3 高斯滤波 |
| `clip.c` | 模块 3：极值截取 |
| `compress.c` | 模块 4：线性压缩（14-bit -> 10-bit） |
| `hist_eq.c` | 模块 5：直方图均衡（10-bit -> 8-bit） |
| `color.c` | 模块 6：灰度 -> 彩色查表（RGB / YUV444） |
| `output.c` | BMP / YUV444 文件写入 |
| `main.c` | 主处理函数：读入字节流，串行执行 6 个模块并输出 |

## 编译

```bash
make              # 默认用 clang，生成 c_model.exe
make CC=gcc       # 使用 gcc
# 或直接编译：
clang -O2 -Wall -std=c99 -o c_model.exe config.c sampling.c gaussian.c \
    clip.c compress.c hist_eq.c color.c output.c main.c
```

## 运行

```bash
# RGB 输出为 BMP
c_model.exe data/1.bin output.bmp

# YUV444 输出为 YUV 文件（扩展名 .yuv 自动切换）
c_model.exe data/1.bin output.yuv
```

输入为原始字节流（UVC 帧，520x202x2 = 210080 字节），例如 `../data/1.bin`。
输出图像尺寸为 260x202。

## 处理流水线

| 模块 | 输入 | 输出 | 说明 |
|------|------|------|------|
| 1 采样 | 字节流 | 14-bit 温度值 | 以半字节为单位配置映射 |
| 2 高斯滤波 | 14-bit | 14-bit | 3x3 核可配置，向外扩展一行/一列保持尺寸 |
| 3 极值截取 | 14-bit | min/max | 多帧平均平滑（N 帧窗口 + step 滞回） |
| 4 线性压缩 | 14-bit | 10-bit | 按 min/max 映射到 0-1023 |
| 5 直方图均衡 | 10-bit | 8-bit | 输出 0-255 灰度 |
| 6 查表 | 8-bit | RGB / YUV444 | 伪彩查表，可配置格式 |

## 可配置参数（数据结构）

所有可配置项集中在 `pipeline_config_t`（见 `config.h`），默认值在
`config.c` 的 `pipeline_config_default()` 中给出：

- **采样** `sampling_config_t`：每个半字节取自源像素 32 位的起始位
  （shift，0-28 的 4 的倍数）、有效位掩码、行列尺寸、边缘脏数据屏蔽
  （skip_top/bottom/left/right，被屏蔽区域用最近有效行列复制）。默认
  取各字节高 4 位（源位 4/12/20/28）拼 16 位取低 14 位，不屏蔽。
- **高斯** `gaussian_config_t`：3x3 权重与归一化因子，默认 `[1 2 1; 2 4 2;
  1 2 1]`、归一化 16。
- **极值截取** `clip_config_t`：`CLIP_MODE_USER`（`user_min`/`user_max`）
  或 `CLIP_MODE_DYNAMIC`（多帧平均平滑：`n_frames` 帧窗口平均 + `step`
  滞回阈值，默认 N=4、step=16）。
- **线性压缩** `compress_config_t`：输出位宽（10）与最大值（1023）。
- **直方图均衡** `hist_eq_config_t`：输出位宽（8）。
- **查表** `color_config_t`：`COLOR_RGB` 或 `COLOR_YUV444`，含 3 个 256 项
  LUT。默认伪彩为分段线性（蓝 -> 青 -> 绿 -> 红 -> 白），YUV 由 BT.601
  定点系数从伪彩 RGB 计算得到。
