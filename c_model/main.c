#include <stdio.h>

#include "config.h"

/* 静态缓冲区（模拟硬件 SRAM，固定尺寸，不 malloc） */
static uint8_t  g_stream[STREAM_BYTES];            /* 输入字节流 */
static uint8_t  g_memory[DATA_BUFFER_BYTES]; /* 采样/高斯/压缩共用缓存（含 pad，stride=IR_STRIDE） */
//static uint8_t  g_gray8[PIXEL_COUNT];              /* 直方图均衡后 8-bit */
//static uint8_t  g_color[PIXEL_COUNT * 3];          /* 查表后 RGB/YUV 交错 */

/* 判断字符串是否以指定后缀结尾（手写，不依赖 string.h） */
static int ends_with(const char *s, const char *suffix) {
    const char *a = s;
    const char *b = suffix;
    while (*a) a++;
    while (*b) b++;
    while (a > s && b > suffix) {
        a--;
        b--;
        if (*a != *b) {
            return 0;
        }
    }
    return (b == suffix);
}

int main(int argc, char *argv[]) {
    pipeline_config_t cfg;
    color_format_t format = COLOR_RGB;
    const char *input_path = "data/1.bin";
    const char *output_path = "output.bmp";
    FILE *f;
    uint32_t stream_bytes;
    uint32_t pixel_count;
    uint16_t min_val = 0, max_val = TEMP14_MAX;
    clip_state_t clip_st;

    /* 命令行：argv[1]=输入文件, argv[2]=输出文件（扩展名 .yuv 则输出 YUV444） */
    if (argc >= 2) {
        input_path = argv[1];
    }
    if (argc >= 3) {
        output_path = argv[2];
    }
    if (ends_with(output_path, ".yuv")) {
        format = COLOR_YUV444;
    }

    pipeline_config_default(&cfg, format);

    /* 读输入字节流 */
    f = fopen(input_path, "rb");
    if (f == NULL) {
        printf("错误：无法打开输入文件 %s\n", input_path);
        return -1;
    }
    stream_bytes = (uint32_t)fread(g_stream, 1, sizeof(g_stream), f);
    fclose(f);

    pixel_count = cfg.sampling.src_width * cfg.sampling.src_height;

    uint16_t *g_data = (uint16_t *)g_memory;  
    uint32_t g_data_bytes = (cfg.sampling.src_height + 2) * (cfg.sampling.src_width + 2) * sizeof(uint16_t);
    
    uint32_t *g_hist = (uint32_t *)(g_memory + g_data_bytes);  /* 直方图统计缓存 */
    g_data_bytes += (TEMP10_MAX + 1) * sizeof(uint32_t);  /* 直方图统计缓存 */

    uint8_t *g_gray8 = (uint8_t *)(g_memory + g_data_bytes);  /* 直方图均衡后 8-bit */
    g_data_bytes += pixel_count * sizeof(uint8_t);  /* 直方图均衡后 8-bit */

    uint8_t *g_color = (uint8_t *)(g_memory + g_data_bytes);  /* 查表后 RGB/YUV 交错 */
    g_data_bytes += pixel_count * 3 * sizeof(uint8_t);  /* 查表后 RGB/YUV 交错 */

    uint16_t *g_cap_raw = (uint16_t *)(g_memory + g_data_bytes);  /* 抓原始帧缓冲区（14-bit 含 pad） */
    g_data_bytes += CAPTURE_RAW_BYTES;

    uint8_t *g_cap_out = (uint8_t *)(g_memory + g_data_bytes);    /* 抓输出帧缓冲区（RGB/YUV 交错） */
    g_data_bytes += CAPTURE_OUT_BYTES;

    //检查配置和memory缓冲区大小
    if (g_data_bytes > sizeof(g_memory)) {
        printf("错误：配置的缓冲区大小 %u 超过预分配的 %zu\n", g_data_bytes, sizeof(g_memory));
        return -1;
    }

    /* 全局寄存器初始化 */
    regs_init(&g_regs);

    /* 模块 1：采样 */
    pixel_count = sampling_run(g_stream, stream_bytes, &cfg.sampling,
                               g_data);
    if (pixel_count != cfg.sampling.src_width *cfg.sampling.src_height) {
        g_regs.status = REG_STATUS_ERR;
        g_regs.error_code = REG_ERR_STREAM_SHORT;
        printf("错误：采样输出 %u 像素（期望 %d），输入字节流尺寸可能不符\n",
               pixel_count, cfg.sampling.src_width *cfg.sampling.src_height);
        return -1;
    }

    /* 计数器清零 trigger：写 1 清零两个计数器 */
    if (g_regs.cnt_clear) {
        g_regs.raw_frame_cnt = 0;
        g_regs.out_frame_cnt = 0;
        g_regs.cnt_clear = 0;
    }

    /* 抓原始帧（采样后、高斯前）：trigger 置位时快照原始 14-bit 数据 */
    if (g_regs.capture_raw) {
        capture_raw_do(&g_regs, g_data, g_cap_raw, CAPTURE_RAW_WORDS);
    }

    /* 每处理一帧原始数据，计数 +1 */
    g_regs.raw_frame_cnt++;

    /* 模块 2：3x3 滤波（高斯/中值，原地，结果紧凑写回采样缓存前部） */
    uint16_t stride = cfg.sampling.src_width + 2;

    filter_run(g_data, cfg.sampling.src_width, cfg.sampling.src_height, cfg.sampling.value_bits, stride,
               &cfg.gaussian);

    /* 模块 3：极值截取（多帧平滑，state 跨帧保持） */
    clip_state_init(&clip_st);
    clip_extremes(g_data, pixel_count, &cfg.clip, &clip_st,
                  &min_val, &max_val);

    /* 模块 4：线性压缩 14-bit -> 10-bit（原地，覆盖 g_data） */
    compress_run(g_data, pixel_count, min_val, max_val, &cfg.compress);

    /* 模块 5：直方图均衡 10-bit -> 8-bit */
    hist_eq_run(g_data, pixel_count, &cfg.hist_eq, g_hist, g_gray8);

    /* 模块 6：查表 RGB/YUV */
    color_run(g_gray8, pixel_count, &cfg.color, g_color);

    /* 抓输出帧（查表后）：trigger 置位时快照最终输出图像 */
    if (g_regs.capture_out) {
        capture_out_do(&g_regs, g_color, g_cap_out, CAPTURE_OUT_BYTES);
    }

    /* 输出 */
    if (cfg.color.format == COLOR_RGB) {
        if (bmp_write(output_path, g_color, IR_WIDTH, IR_HEIGHT) != 0) {
            printf("错误：无法写输出文件 %s\n", output_path);
            return -1;
        }
    } else {
        if (yuv_write(output_path, g_color, IR_WIDTH, IR_HEIGHT) != 0) {
            printf("错误：无法写输出文件 %s\n", output_path);
            return -1;
        }
    }

    /* 每输出一帧，计数 +1 */
    g_regs.out_frame_cnt++;

    printf("完成：%s -> %s（%d x %d，极值 [%u, %u]，raw帧=%u out帧=%u 状态=%u 错误=0x%X）\n",
           input_path, output_path, IR_WIDTH, IR_HEIGHT, min_val, max_val,
           g_regs.raw_frame_cnt, g_regs.out_frame_cnt, g_regs.status, g_regs.error_code);
    return 0;
}
