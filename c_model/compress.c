#include "config.h"

/* 模块 4：线性压缩
 * 根据极值把 [min_val, max_val] 线性映射到 [0, out_max]（10-bit），
 * 超出范围的部分截断，全部使用定点整数运算。结果原地写回 img，输入
 * 输出共用同一缓存（输出 10-bit <= 输入 14-bit，逐像素顺序处理安全）。 */
void compress_run(uint16_t *img, uint32_t count,
                  uint16_t min_val, uint16_t max_val,
                  const compress_config_t *cfg) {
    uint32_t i;
    uint32_t range = (uint32_t)max_val - min_val;

    if (range == 0) {
        for (i = 0; i < count; i++) {
            img[i] = 0;
        }
        return;
    }

    for (i = 0; i < count; i++) {
        uint16_t p = img[i];
        uint32_t v;

        if (p <= min_val) {
            v = 0;
        } else if (p >= max_val) {
            v = cfg->out_max;
        } else {
            v = ((uint32_t)(p - min_val) * cfg->out_max + range / 2) / range;
        }
        img[i] = (uint16_t)v;
    }
}
