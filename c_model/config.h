#ifndef C_MODEL_CONFIG_H
#define C_MODEL_CONFIG_H

#include <stdint.h>

/* ======================================================================
 * 红外图像处理流水线 C 模型 —— 统一头文件
 *
 * 用于芯片设计的 C 语言参考模型。算法全部手写，使用定点整数与静态
 * 数组（不 malloc、不用 math.h 浮点），仅依赖标准库的 stdint.h（固定
 * 宽度类型）与 stdio.h（文件 I/O，见 main.c / output.c）。
 *
 * 所有可配置参数一律通过下面的结构体描述，默认值见 config.c。
 * ====================================================================== */

/* ----- 图像尺寸（与红外传感器规格一致） ----- */
#define IR_WIDTH         260    /* 像素列数 */
#define IR_HEIGHT        202    /* 像素行数（与源帧行数一致，不丢弃最后一行） */
#define IR_UVC_WIDTH     520    /* UVC 逻辑宽度，字节流每行 520*2 字节 */

#define PIXEL_COUNT      (IR_WIDTH * IR_HEIGHT)              /* 52520 */
#define STREAM_BYTES     (IR_UVC_WIDTH * IR_HEIGHT * 2)      /* 210080 */

/* 采样/高斯共用缓存：每行左右各预留 1 列 pad、上下各预留 1 行 pad */
#define IR_STRIDE        (IR_WIDTH + 2)                      /* 262 */
#define DATA_BUFFER_BYTES  0x100000  
//#define DATA_BUFFER_WORDS  DATA_BUFFER_BYTES/2 

/* ----- 位宽 ----- */
#define TEMP14_BITS      14
#define TEMP14_MAX       0x3FFF   /* 16383 */
#define TEMP10_BITS      10
#define TEMP10_MAX       0x03FF   /* 1023 */
#define GRAY8_MAX        0x00FF   /* 255 */

/* ======================================================================
 * 模块 1：接口温度值采样
 * 字节流 -> 14-bit 温度值。映射以半字节（4bit）为单位配置：每个温度值
 * 由 4 个半字节组成。源像素为 4 字节（32 位，按字节流顺序从低到高编号
 * 0-31），第 i 个半字节取自源第 shift[i] 位开始的 4 位，固定拼入
 * 16-bit 值的第 (3-i)*4 位（第 0 个半字节最高、第 3 个最低）。
 * 可配置屏蔽上下左右边缘的脏数据行/列（skip_top/bottom/left/right），
 * 被屏蔽区域用最近的有效行/列数据复制填充。
 * ====================================================================== */
#define NIBBLE_COUNT     4

typedef struct {
    uint8_t  shift[NIBBLE_COUNT]; /* 各半字节取自源32位的起始位(0/4/.../28) */
    uint8_t  bytes_per_pixel;           /* 每红外像素字节数 = 4 */
    uint16_t value_bits;                /* 温度值有效位数 = 14 */
    uint16_t src_width;                 /* 每行红外像素数 = 260 */
    uint16_t src_height;                /* 行数 = 202（输出与源一致，不丢弃） */
    uint16_t skip_top;                  /* 屏蔽顶部行数（脏数据，用有效行复制） */
    uint16_t skip_bottom;               /* 屏蔽底部行数 */
    uint16_t skip_left;                 /* 屏蔽左侧列数 */
    uint16_t skip_right;                /* 屏蔽右侧列数 */
} sampling_config_t;

/* ======================================================================
 * 模块 2：3x3 高斯滤波，滤波核可配置
 * 输入为采样缓存（stride = width + 2），已预留上下各 1 行、左右各 1 列
 * pad 空间，滤波前填充 pad，不另开辟缓存。
 * ====================================================================== */
typedef struct {
    int16_t  kernel[9];   /* 3x3 权重，行优先 */
    uint16_t norm;        /* 归一化因子（权重之和） */
} gaussian_config_t;

/* ======================================================================
 * 模块 3：极值截取（多帧平均平滑）
 * 两种方式：用户配置 min/max，或动态统计。动态统计时每帧取简单
 * min/max，维护 N 帧滑动窗口，用窗口内极值的平均值更新当前极值；
 * 更新条件为变化量 >= step（滞回），满足则直接设为平均值。
 * ====================================================================== */
#define CLIP_MAX_FRAMES  16    /* 平均帧数 N 的上限 */

typedef enum {
    CLIP_MODE_USER = 0,      /* 用户配置 */
    CLIP_MODE_DYNAMIC = 1    /* 动态统计调节 */
} clip_mode_t;

typedef struct {
    clip_mode_t mode;
    uint16_t    user_min;     /* 用户配置的最小值 */
    uint16_t    user_max;     /* 用户配置的最大值 */
    uint8_t     n_frames;     /* 平均帧数 N（1/2/4/8/16） */
    uint16_t    step;         /* 更新阈值：变化量 >= step 才更新，默认 16 */
} clip_config_t;

/* 模块 3 运行时状态（跨帧保持） */
#define CLIP_USE_LOWPASS 0  /* 0:滑动窗口平均, 1:低通滤波 */
#if CLIP_USE_LOWPASS == 0
typedef struct {
    uint16_t min_buf[CLIP_MAX_FRAMES];  /* 滑动窗口内各帧 min */
    uint16_t max_buf[CLIP_MAX_FRAMES];  /* 滑动窗口内各帧 max */
    uint32_t sum_min;                   /* 窗口 min 之和 */
    uint32_t sum_max;                   /* 窗口 max 之和 */
    uint8_t  cnt;                       /* 已累积帧数 0..N */
    uint8_t  write_idx;                 /* 环形写位置 */
    uint16_t cur_min;                   /* 当前输出 min */
    uint16_t cur_max;                   /* 当前输出 max */
} clip_state_t;
#else
//采用低通滤波方式
typedef struct {
    uint8_t  cnt;                       /* 已累积帧数 0..N */
    uint16_t cur_min;                   /* 当前输出 min */
    uint16_t cur_max;                   /* 当前输出 max */
} clip_state_t;
 #endif
/* ======================================================================
 * 模块 4：线性压缩，根据极值把温度值缩到 10-bit
 * ====================================================================== */
typedef struct {
    uint8_t  out_bits;   /* 输出位宽 = 10 */
    uint16_t out_max;    /* 输出最大值 = 1023 */
} compress_config_t;

/* ======================================================================
 * 模块 5：直方图均衡，10-bit -> 8-bit 灰度
 * ====================================================================== */
typedef struct {
    uint8_t out_bits;    /* 输出位宽 = 8 */
} hist_eq_config_t;

/* ======================================================================
 * 模块 6：灰度 -> 彩色查表（RGB 或 YUV444）
 * ====================================================================== */
typedef enum {
    COLOR_RGB = 0,
    COLOR_YUV444 = 1
} color_format_t;

typedef struct {
    color_format_t format;
    uint8_t lut0[256];   /* RGB: R, YUV: Y */
    uint8_t lut1[256];   /* RGB: G, YUV: U */
    uint8_t lut2[256];   /* RGB: B, YUV: V */
} color_config_t;

/* ======================================================================
 * 全局控制/状态寄存器（模拟芯片内存映射寄存器，见 registers.c）
 * ====================================================================== */

/* 运行状态字 */
#define REG_STATUS_OK      0u    /* 正常 */
#define REG_STATUS_ERR     1u    /* 异常 */

/* 最后错误字（REG_ERR_*，异常时置位） */
#define REG_ERR_NONE          0x00000000u  /* 无错误 */
#define REG_ERR_STREAM_SHORT  0x00000001u  /* 输入字节流尺寸不足 */
#define REG_ERR_BUF_OVERFLOW  0x00000002u  /* 内存缓冲区越界 */
#define REG_ERR_CAPTURE_BUSY  0x00000004u  /* 抓帧忙：上一帧数据未读走 */

/* 抓帧缓冲区（位于 g_memory 末尾之后，见 main.c 切分） */
#define CAPTURE_RAW_WORDS   ((IR_HEIGHT + 2) * IR_STRIDE)   /* 原始 14-bit 含 pad */
#define CAPTURE_RAW_BYTES   (CAPTURE_RAW_WORDS * 2)
#define CAPTURE_OUT_BYTES   (PIXEL_COUNT * 3)               /* 输出 RGB/YUV 交错 */

/* 全局寄存器（模拟硬件，跨帧保持） */
typedef struct {
    volatile uint32_t raw_frame_cnt;  /* R  已抓取原始帧数（每处理一帧 +1） */
    volatile uint32_t out_frame_cnt;  /* R  已输出帧数（每输出一帧 +1） */
    volatile uint32_t cnt_clear;      /* W  写 1 清零两个计数器（执行后清 0） */
    volatile uint32_t capture_raw;    /* RW 写 1 抓下一帧原始数据，抓完清 0（读清） */
    volatile uint32_t capture_out;    /* RW 写 1 抓下一帧输出图像，抓完清 0（读清） */
    volatile uint32_t status;         /* R  运行状态：0 正常，1 异常 */
    volatile uint32_t error_code;     /* R  最后错误字（REG_ERR_*） */
} regs_t;

/* 全局寄存器实例（定义在 registers.c） */
extern regs_t g_regs;

/* 寄存器初始化 */
void regs_init(regs_t *r);

/* 抓帧动作：把一帧数据快照到抓帧缓冲区，完成后清 trigger */
void capture_raw_do(regs_t *r, const uint16_t *src, uint16_t *dst, uint32_t words);
void capture_out_do(regs_t *r, const uint8_t *src, uint8_t *dst, uint32_t bytes);

/* ======================================================================
 * 总配置
 * ====================================================================== */
typedef struct {
    sampling_config_t  sampling;
    gaussian_config_t  gaussian;
    clip_config_t      clip;
    compress_config_t  compress;
    hist_eq_config_t   hist_eq;
    color_config_t     color;
} pipeline_config_t;

/* 用默认参数初始化配置，输出格式由 format 决定 */
void pipeline_config_default(pipeline_config_t *cfg, color_format_t format);

/* 生成默认伪彩查表（分段线性：蓝 -> 青 -> 绿 -> 红 -> 白） */
void color_config_init(color_config_t *cfg, color_format_t format);

/* ----- 各模块处理函数声明 ----- */

/* 模块 1：采样，返回输出的温度值个数 */
uint32_t sampling_run(const uint8_t *stream, uint32_t stream_bytes,
                      const sampling_config_t *cfg, uint16_t *temp14_out);

/* 模块 2：3x3 高斯滤波，输入含 pad 的采样缓存（stride = width + 2），
 * 结果紧凑写回同一缓存前部（原地） */
void gaussian_run(uint16_t *img, uint16_t width, uint16_t height, uint16_t bits,
                  uint16_t stride, const gaussian_config_t *cfg);

/* 模块 3 状态初始化（cur_min=0, cur_max=TEMP14_MAX） */
void clip_state_init(clip_state_t *st);

/* 模块 3：极值截取，输出 min/max（state 跨帧保持） */
void clip_extremes(const uint16_t *img, uint32_t count,
                   const clip_config_t *cfg, clip_state_t *st,
                   uint16_t *min_out, uint16_t *max_out);

/* 模块 4：线性压缩 14-bit -> 10-bit（原地，输入输出同一缓存） */
void compress_run(uint16_t *img, uint32_t count,
                  uint16_t min_val, uint16_t max_val,
                  const compress_config_t *cfg);

/* 模块 5：直方图均衡 10-bit -> 8-bit */
void hist_eq_run(const uint16_t *img, uint32_t count, uint32_t *hist, uint8_t *gray8_out);

/* 模块 6：查表映射，输出交错 3 通道（RGB 或 YUV） */
void color_run(const uint8_t *gray8, uint32_t count,
               const color_config_t *cfg, uint8_t *out);

/* 文件输出：写 24-bit BMP / YUV444 平面文件，失败返回非 0 */
int bmp_write(const char *path, const uint8_t *rgb,
              uint16_t width, uint16_t height);
int yuv_write(const char *path, const uint8_t *yuv444,
              uint16_t width, uint16_t height);

#endif /* C_MODEL_CONFIG_H */
