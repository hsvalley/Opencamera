#include <stddef.h>
#include <stdio.h>

#include "config.h"

/* 阶段转储：每个模块处理完，把该模块的输出写成
 *   <输入文件名去扩展名>_<模块名>.bin
 * 的文件（原始小端字节，便于用 Python/numpy 离线比对）。例如输入
 * data/1.bin 会得到 data/1_sampling.bin、data/1_gaussian.bin ……
 * 需要精简构建时加 -DDUMP_STAGES=0 关闭。 */
#ifndef DUMP_STAGES
#define DUMP_STAGES 1
#endif

#define DUMP_PATH_MAX   512   /* 转储文件名的缓冲区字节数 */

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

#if DUMP_STAGES
/* ---------------- 阶段转储辅助（手写字符串处理，不依赖 string.h） -------- */

/* 取输入路径去掉扩展名后的部分（保留目录）作为转储前缀。
 * "data/1.bin" -> "data/1"，"1.bin" -> "1"，"1" -> "1"。 */
static void path_stem(const char *path, char *out, size_t out_size) {
    size_t n = 0;
    size_t cut;
    size_t i;

    if (out_size == 0) {
        return;
    }
    while (path[n] != '\0') {
        n++;
    }
    cut = n;                                   /* 默认整段保留（无扩展名） */
    for (i = n; i > 0; i--) {
        char ch = path[i - 1];
        if (ch == '/' || ch == '\\') {
            break;                             /* 已越过目录分隔符，无扩展名 */
        }
        if (ch == '.') {
            cut = i - 1;
            break;
        }
    }
    if (cut >= out_size) {
        cut = out_size - 1;
    }
    for (i = 0; i < cut; i++) {
        out[i] = path[i];
    }
    out[cut] = '\0';
}

/* 有界追加：把 src 追加到 dst[*len]，并补 '\0'；空间不足返回 -1。 */
static int append_str(char *dst, size_t cap, size_t *len, const char *src) {
    while (*src != '\0') {
        if (*len + 1 >= cap) {
            return -1;
        }
        dst[(*len)++] = *src++;
        dst[*len] = '\0';
    }
    return 0;
}

/* 拼接转储文件名 <前缀>_<模块名>.bin。成功返回 0，名字过长返回 -1。 */
static int dump_name(char *out, size_t cap, const char *stem, const char *module) {
    size_t len = 0;

    if (cap < 8) {
        return -1;
    }
    out[0] = '\0';
    if (append_str(out, cap, &len, stem) != 0) return -1;
    if (append_str(out, cap, &len, "_") != 0) return -1;
    if (append_str(out, cap, &len, module) != 0) return -1;
    if (append_str(out, cap, &len, ".bin") != 0) return -1;
    return 0;
}

/* 创建转储文件，成功返回 FILE* 并回填文件名；失败打印警告并返回 NULL。 */
static FILE *open_dump(const char *stem, const char *module,
                       char *name, size_t cap) {
    FILE *f;

    if (dump_name(name, cap, stem, module) != 0) {
        printf("警告：转储文件名过长，已跳过 %s\n", module);
        return NULL;
    }
    f = fopen(name, "wb");
    if (f == NULL) {
        printf("警告：无法写阶段转储 %s\n", name);
        return NULL;
    }
    return f;
}

/* 转储一段连续内存的阶段输出（原样写 bytes 字节）。 */
static int dump_blob(const char *stem, const char *module,
                     const void *data, uint32_t bytes) {
    char name[DUMP_PATH_MAX];
    FILE *f = open_dump(stem, module, name, sizeof(name));

    if (f == NULL) {
        return -1;
    }
    if (bytes != 0) {
        fwrite(data, 1, bytes, f);
    }
    fclose(f);
    printf("  转储 %s（%u 字节）\n", name, (unsigned)bytes);
    return 0;
}

/* 转储带 pad 布局的阶段输出：只导出有效区 [1..height][1..width]，紧凑
 * 行优先、每像素 2 字节（uint16，本机小端）。 */
static int dump_rows(const char *stem, const char *module, const uint16_t *img,
                     uint16_t width, uint16_t height, uint16_t stride) {
    char name[DUMP_PATH_MAX];
    uint16_t row[IR_WIDTH];
    uint16_t y, x;
    uint32_t bytes;
    FILE *f;

    if (width > IR_WIDTH) {
        printf("警告：转储宽度 %u 超过 IR_WIDTH，已跳过 %s\n",
               (unsigned)width, module);
        return -1;
    }
    f = open_dump(stem, module, name, sizeof(name));
    if (f == NULL) {
        return -1;
    }
    for (y = 0; y < height; y++) {
        const uint16_t *src = img + (uint32_t)(y + 1) * stride + 1;
        for (x = 0; x < width; x++) {
            row[x] = src[x];
        }
        fwrite(row, sizeof(uint16_t), width, f);
    }
    fclose(f);
    bytes = (uint32_t)width * height * (uint32_t)sizeof(uint16_t);
    printf("  转储 %s（%u x %u，uint16，%u 字节）\n",
           name, (unsigned)width, (unsigned)height, (unsigned)bytes);
    return 0;
}
#endif /* DUMP_STAGES */

int main(int argc, char *argv[]) {
    pipeline_config_t cfg;
    color_format_t format = COLOR_RGB;
    const char *input_path = "data/1.bin";
    const char *output_path = "output.bmp";
    FILE *f;
    uint32_t stream_bytes;
    uint32_t pixel_count;
    uint16_t stride;
    uint16_t min_val = 0, max_val = TEMP14_MAX;
    clip_state_t clip_st;
#if DUMP_STAGES
    char stem[DUMP_PATH_MAX];        /* 转储文件前缀（输入文件名去扩展名） */
    const char *filter_name;
#endif

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
    stride = (uint16_t)(cfg.sampling.src_width + 2);   /* 采样缓存每行 uint16 数（含 pad） */

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

#if DUMP_STAGES
    path_stem(input_path, stem, sizeof(stem));
#endif

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

#if DUMP_STAGES
    /* 模块 1 输出：14-bit 温度值，有效区内紧凑导出为 width x height */
    dump_rows(stem, "sampling", g_data,
              cfg.sampling.src_width, cfg.sampling.src_height, stride);
#endif

    /* 模块 2：3x3 滤波（高斯/中值，原地，结果紧凑写回采样缓存前部） */
    filter_run(g_data, cfg.sampling.src_width, cfg.sampling.src_height, cfg.sampling.value_bits, stride,
               &cfg.gaussian);

#if DUMP_STAGES
    /* 模块 2 输出：14-bit，紧凑 width x height；模块名按实际滤波方式命名 */
    filter_name = (cfg.gaussian.filter_mode == FILTER_MEDIAN) ? "median" : "gaussian";
    dump_blob(stem, filter_name, g_data, pixel_count * (uint32_t)sizeof(uint16_t));
#endif

    /* 模块 3：极值截取（多帧平滑，state 跨帧保持） */
    clip_state_init(&clip_st);
    clip_extremes(g_data, pixel_count, &cfg.clip, &clip_st,
                  &min_val, &max_val);

#if DUMP_STAGES
    {
        /* 模块 3 输出：本帧的 [min, max] 两个 uint16（数据本身不修改） */
        uint16_t clip_dump[2];
        clip_dump[0] = min_val;
        clip_dump[1] = max_val;
        dump_blob(stem, "clip", clip_dump, (uint32_t)sizeof(clip_dump));
    }
#endif

    /* 模块 4：线性压缩 14-bit -> 10-bit（原地，覆盖 g_data） */
    compress_run(g_data, pixel_count, min_val, max_val, &cfg.compress);

#if DUMP_STAGES
    /* 模块 4 输出：10-bit，紧凑 width x height */
    dump_blob(stem, "compress", g_data, pixel_count * (uint32_t)sizeof(uint16_t));
#endif

    /* 模块 5：直方图均衡 10-bit -> 8-bit */
    hist_eq_run(g_data, pixel_count, &cfg.hist_eq, g_hist, g_gray8);

#if DUMP_STAGES
    /* 模块 5 输出：8-bit 灰度，紧凑 width x height */
    dump_blob(stem, "hist_eq", g_gray8, pixel_count);
#endif

    /* 模块 6：查表 RGB/YUV */
    color_run(g_gray8, pixel_count, &cfg.color, g_color);

#if DUMP_STAGES
    /* 模块 6 输出：3 字节/像素交错（RGB 或 YUV444，取决于输出文件扩展名） */
    dump_blob(stem, "color", g_color, pixel_count * 3u);
#endif

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
