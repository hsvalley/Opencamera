#include "config.h"

/* 填充采样缓存上下各 1 行、左右各 1 列 pad（复制最近的有效行/列）。 */
static void fill_pads(uint16_t *img, uint16_t width, uint16_t height, uint16_t stride) {
    int y, x;
    /* 填顶部/底部 pad 行：复制第 1 行 / 第 height 行的数据 */
    for (x = 1; x <= width; x++) {
        img[0 * stride + x] = img[1 * stride + x];
        img[(height + 1) * stride + x] = img[height * stride + x];
    }
    /* 填左/右 pad 列：复制第 1 列 / 第 width 列（含四角） */
    for (y = 0; y < height + 2; y++) {
        img[y * stride + 0] = img[y * stride + 1];
        img[y * stride + width + 1] = img[y * stride + width];
    }
}

/* 对 9 个 uint16 排序（插入排序），返回中位数（第 5 个）。 */
static uint16_t median9(uint16_t w[9]) {
    int i, j;
    for (i = 1; i < 9; i++) {
        uint16_t key = w[i];
        for (j = i - 1; j >= 0 && w[j] > key; j--) {
            w[j + 1] = w[j];
        }
        w[j + 1] = key;
    }
    return w[4];
}

/* 模块 2：3x3 高斯滤波，滤波核可配置。
 * 输入 img 为采样缓存（stride = width + 2），数据位于内部
 * [1..height][1..width]，上下各 1 行、左右各 1 列为空 pad。先填充 pad
 * （复制最近的有效行/列），再做 3x3 卷积，结果紧凑写回 img 前部
 * [0..height*width-1]，与采样输入共用同一缓存。因 stride > width，紧凑
 * 写回地址始终在后续读取地址之前，原地处理不会覆盖未读数据。定点整数。 */
void gaussian_run(uint16_t *img, uint16_t width, uint16_t height, uint16_t bits,
                  uint16_t stride, const gaussian_config_t *cfg) {
    int y, x, dy, dx;
    uint16_t max_val = (1u << bits) - 1u;

    fill_pads(img, width, height, stride);

    /* 3x3 卷积，结果紧凑写回 img 前部（原地复用采样缓存） */
    for (y = 0; y < height; y++) {
        for (x = 0; x < width; x++) {
            int32_t acc = 0;
            for (dy = -1; dy <= 1; dy++) {
                for (dx = -1; dx <= 1; dx++) {
                    acc += (int32_t)img[(y + 1 + dy) * stride + (x + 1 + dx)]
                         * cfg->kernel[(dy + 1) * 3 + (dx + 1)];
                }
            }
            {
                int32_t v = (acc + (int32_t)(cfg->norm / 2)) / cfg->norm;
                if (v < 0) v = 0;
                if (v > max_val) v = max_val;
                img[y * width + x] = (uint16_t)v;
            }
        }
    }
}

/* 模块 2：3x3 中值滤波，取窗口内 9 个像素的中位数。
 * 与高斯相同：填充 pad 后逐像素取 3x3 窗口，结果紧凑写回 img 前部
 * [0..height*width-1]。中位数取自输入值，无需位宽裁剪。 */
void median_run(uint16_t *img, uint16_t width, uint16_t height, uint16_t stride) {
    int y, x, dy, dx, n;
    uint16_t w[9];

    fill_pads(img, width, height, stride);

    for (y = 0; y < height; y++) {
        for (x = 0; x < width; x++) {
            n = 0;
            for (dy = -1; dy <= 1; dy++) {
                for (dx = -1; dx <= 1; dx++) {
                    w[n++] = img[(y + 1 + dy) * stride + (x + 1 + dx)];
                }
            }
            img[y * width + x] = median9(w);
        }
    }
}

/* 模块 2：滤波分发，按 cfg->filter_mode 选择高斯或中值。 */
void filter_run(uint16_t *img, uint16_t width, uint16_t height, uint16_t bits,
                uint16_t stride, const gaussian_config_t *cfg) {
    if (cfg->filter_mode == FILTER_MEDIAN) {
        median_run(img, width, height, stride);
    } else {
        gaussian_run(img, width, height, bits, stride, cfg);
    }
}
