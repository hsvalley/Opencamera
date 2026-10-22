# 红外图像处理流水线 C 模型

用于芯片设计的 C 语言参考模型，实现红外图像处理流水线。算法全部手写，
使用定点整数与静态数组（不 malloc、不用 math.h 浮点），仅依赖标准库的
`stdint.h`（固定宽度类型）、`stddef.h`（`NULL`）与 `stdio.h`（文件 I/O）。

## 目录结构

| 文件 | 职责 |
|------|------|
| `config.h` | 类型、常量、各模块配置结构体与函数声明 |
| `config.c` | 默认配置初始化 |
| `registers.c` | 寄存器模型：`g_regs` 实例、帧计数器、抓帧 trigger（`capture_raw_do` / `capture_out_do`）、状态与错误码 |
| `sampling.c` | 模块 1：接口温度值采样 |
| `gaussian.c` | 模块 2：3x3 滤波（高斯 / 中值） |
| `clip.c` | 模块 3：极值截取（滑动窗口平均 / 低通） |
| `compress.c` | 模块 4：线性压缩（14-bit -> 10-bit） |
| `hist_eq.c` | 模块 5：直方图均衡（10-bit -> 8-bit） |
| `color.c` | 模块 6：灰度 -> 彩色查表（RGB / YUV444） |
| `output.c` | BMP / YUV444 文件写入 |
| `main.c` | 主处理函数：读入字节流，串行执行 6 个模块并输出 |

## 编译

全部源码为 10 个 `.c`（`main.c` 依赖 `registers.c`，缺一个都链接不过）+ 统一头文件
`config.h`，语言标准 C99。三种方式任选其一。

### 方式 A：clang（与仓库内 `c_model.exe` 的产线一致）

clang 在 Windows 上默认 target 是 `x86_64-pc-windows-msvc`，默认静态链接 MSVC CRT
（等价 `/MT`）。因此必须先进入 **x64 Native Tools Command Prompt for VS 2022**
（或已执行过 `vcvars64.bat`），让 clang 找到 MSVC 头文件与库：

```bat
cd c_model
clang -O2 -Wall -Wextra -std=c99 -o c_model.exe ^
  config.c sampling.c gaussian.c clip.c compress.c hist_eq.c ^
  color.c output.c registers.c main.c
```

### 方式 B：MSVC cl.exe

同一个开发者命令行里（`/MT` 为静态 CRT，可换成 `/MD` 动态 CRT）：

```bat
cl /nologo /O2 /MT /W3 /Fe:c_model.exe ^
  config.c sampling.c gaussian.c clip.c compress.c hist_eq.c ^
  color.c output.c registers.c main.c
```

### 方式 C：gcc / MinGW-w64（Makefile）

```bash
make              # 默认 clang
make CC=gcc       # 使用 gcc
make clean
```

Windows 上 `make` 可从 Git Bash / MSYS2 里取，或用 `mingw32-make`；`make clean`
用的是 `rm -f`，纯 cmd 下改用 `del /q *.o c_model.exe`。MinGW 产物用 MinGW CRT，
二进制特征与 A/B 不同，但算法结果一致。

> 仓库内已有的 `c_model.exe` 是方式 A/B（x64 MSVC CRT 静态链接，`link.exe` 14.44）
> 的产物；重新编译后请覆盖它，并跑一次 `c_model.exe data/1.bin output.bmp` 校验。
> 注意 `output.bmp` 是相对当前工作目录解析的，从仓库根目录执行即为
> `c_model\c_model.exe data\1.bin out.bmp`。

## 运行

```bash
# RGB 输出为 BMP
c_model.exe data/1.bin output.bmp

# YUV444 输出为 YUV 文件（扩展名 .yuv 自动切换）
c_model.exe data/1.bin output.yuv
```

输入为原始字节流（UVC 帧，520x202x2 = 210080 字节），例如 `../data/1.bin`。
输出图像尺寸为 260x202。

## 阶段转储（调试用）

每跑完一个模块，`main.c` 会把该模块的输出写成
`<输入文件名去扩展名>_<模块名>.bin`，**与输入文件同目录**。例如
`c_model.exe data/1.bin output.bmp` 会额外得到：

| 文件 | 内容 | 字节数 |
|------|------|--------|
| `data/1_sampling.bin` | 模块 1 输出，14-bit 温度值，`260x202`，uint16 小端 | 105040 |
| `data/1_gaussian.bin` | 模块 2 输出，14-bit，`260x202` uint16；滤波方式为中值时文件名改为 `1_median.bin` | 105040 |
| `data/1_clip.bin` | 模块 3 输出，本帧 `[min, max]` 两个 uint16 | 4 |
| `data/1_compress.bin` | 模块 4 输出，10-bit，`260x202` uint16 | 105040 |
| `data/1_hist_eq.bin` | 模块 5 输出，8-bit 灰度，`260x202` | 52520 |
| `data/1_color.bin` | 模块 6 输出，RGB 或 YUV444 交错，`260x202x3` | 157560 |

- 采样缓存本身是带 pad 的 `(w+2)x(h+2)` 布局，转储时只导出有效区
  `[1..h][1..w]`，因此前两级可直接 `numpy.frombuffer(..., dtype='<u2').reshape(202, 260)`。
- 所有转储均为原始字节、无文件头；`clip` 是 4 字节的最小/最大值，不是图像。
- 不需要转储时用 `-DDUMP_STAGES=0` 编译即可完全去掉这部分代码（不影响正常输出）。

## 处理流水线

| 模块 | 输入 | 输出 | 说明 |
|------|------|------|------|
| 1 采样 | 字节流 | 14-bit 温度值 | 以半字节为单位配置映射 |
| 2 滤波 | 14-bit | 14-bit | 3x3 高斯（核可配置）或中值，向外扩展一行/一列保持尺寸 |
| 3 极值截取 | 14-bit | min/max | 多帧平滑：滑动窗口平均 + step 滞回，或一阶低通 |
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
- **滤波** `gaussian_config_t`：`filter_mode`（`FILTER_GAUSSIAN` 或
  `FILTER_MEDIAN`，默认高斯）、3x3 权重与归一化因子，默认 `[1 2 1; 2 4 2;
  1 2 1]`、归一化 16。
- **极值截取** `clip_config_t`：`CLIP_MODE_USER`（`user_min`/`user_max`）
  或 `CLIP_MODE_DYNAMIC`（`calc_mode`：`CLIP_CALC_AVG` 滑动窗口平均 + `step`
  滞回，或 `CLIP_CALC_LOWPASS` 一阶低通，默认低通；`n_frames` 平滑帧数，
  默认 N=4、step=16）。
- **线性压缩** `compress_config_t`：输出位宽（10）与最大值（1023）。
- **直方图均衡** `hist_eq_config_t`：输出位宽（8）、`reverse`（0 升序 /
  1 反相，默认反相）。
- **查表** `color_config_t`：`COLOR_RGB` 或 `COLOR_YUV444`，含 3 个 256 项
  LUT。默认伪彩为分段线性（蓝 -> 青 -> 绿 -> 红 -> 白），YUV 由 BT.601
  定点系数从伪彩 RGB 计算得到。
