#include "config.h"

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

    /* 1. 填顶部/底部 pad 行：复制第 1 行 / 第 height 行的数据 */
    for (x = 1; x <= width; x++) {
        img[0 * stride + x] = img[1 * stride + x];
        img[(height + 1) * stride + x] = img[height * stride + x];
    }

    /* 2. 填左/右 pad 列：复制第 1 列 / 第 width 列（含四角） */
    for (y = 0; y < height + 2; y++) {
        img[y * stride + 0] = img[y * stride + 1];
        img[y * stride + width + 1] = img[y * stride + width];
    }

    /* 3. 3x3 卷积，结果紧凑写回 img 前部（原地复用采样缓存） */
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
