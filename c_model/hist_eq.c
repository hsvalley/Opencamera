#include "config.h"

/* 模块 5：直方图均衡，10-bit -> 8-bit 灰度。
 * 在 10-bit 全范围上做直方图均衡，输出 0-255 灰度；cfg->reverse 为 1 时
 * 输出反相（灰度降序，高温=暗）。 */
void hist_eq_run(const uint16_t *img, uint32_t count, const hist_eq_config_t *cfg, uint32_t *hist, uint8_t *gray8_out) {
    uint32_t i, cdf_min = 0;

    for (i = 0; i <= TEMP10_MAX; i++) {
        hist[i] = 0;
    }
    
    for (i = 0; i < count; i++) {
        hist[img[i]]++;
    }

    for (i = 1; i <= TEMP10_MAX; i++) {
        hist[i] += hist[i - 1];
    }

    /* cdf_min = 第一个非零 cdf 值 */
    for (i = 0; i <= TEMP10_MAX; i++) {
        if (hist[i] > 0) {
            cdf_min = hist[i];
            break;
        }
    }

    /* 无有效数据或全图同值时输出全 0 */
    if (count == 0 || count == cdf_min) {
        for (i = 0; i < count; i++) {
            gray8_out[i] = 0;
        }
        return;
    }

    for (i = 0; i < count; i++) {
        uint32_t c = hist[img[i]];
        uint32_t gray = (c - cdf_min) * 255u / (count - cdf_min);
        gray8_out[i] = (uint8_t)(cfg->reverse ? (255u - gray) : gray);
    }
}
