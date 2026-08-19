#include "config.h"

/* 生成默认伪彩 RGB 查表（分段线性：蓝 -> 青 -> 绿 -> 红 -> 白） */
static void pseudo_rgb_lut(uint8_t r[256], uint8_t g[256], uint8_t b[256]) {
    int i;
    for (i = 0; i < 256; i++) {
        if (i < 64) {
            r[i] = 0;
            g[i] = 0;
            b[i] = (uint8_t)(i * 4);
        } else if (i < 128) {
            r[i] = (uint8_t)((i - 64) * 4);
            g[i] = 0;
            b[i] = (uint8_t)(255 - (i - 64) * 4);
        } else if (i < 192) {
            r[i] = 255;
            g[i] = (uint8_t)((i - 128) * 4);
            b[i] = 0;
        } else {
            r[i] = 255;
            g[i] = 255;
            b[i] = (uint8_t)((i - 192) * 4);
        }
    }
}

/* BT.601 定点系数：RGB -> YUV，U/V 加 128 偏移 */
static void rgb_to_yuv_lut(const uint8_t r[256], const uint8_t g[256],
                           const uint8_t b[256],
                           uint8_t y[256], uint8_t u[256], uint8_t v[256]) {
    int i;
    for (i = 0; i < 256; i++) {
        int R = r[i], G = g[i], B = b[i];
        int Y = (77 * R + 150 * G + 29 * B) >> 8;
        int U = ((-43 * R - 85 * G + 128 * B) >> 8) + 128;
        int V = ((128 * R - 107 * G - 21 * B) >> 8) + 128;

        y[i] = (uint8_t)(Y < 0 ? 0 : (Y > 255 ? 255 : Y));
        u[i] = (uint8_t)(U < 0 ? 0 : (U > 255 ? 255 : U));
        v[i] = (uint8_t)(V < 0 ? 0 : (V > 255 ? 255 : V));
    }
}

void color_config_init(color_config_t *cfg, color_format_t format) {
    uint8_t r[256], g[256], b[256];
    int i;

    cfg->format = format;
    pseudo_rgb_lut(r, g, b);

    if (format == COLOR_RGB) {
        for (i = 0; i < 256; i++) {
            cfg->lut0[i] = r[i];
            cfg->lut1[i] = g[i];
            cfg->lut2[i] = b[i];
        }
    } else {
        rgb_to_yuv_lut(r, g, b, cfg->lut0, cfg->lut1, cfg->lut2);
    }
}

/* 模块 6：查表映射，8-bit 灰度 -> RGB 或 YUV444（交错 3 通道） */
void color_run(const uint8_t *gray8, uint32_t count,
               const color_config_t *cfg, uint8_t *out) {
    uint32_t i;
    for (i = 0; i < count; i++) {
        uint8_t g = gray8[i];
        out[i * 3 + 0] = cfg->lut0[g];
        out[i * 3 + 1] = cfg->lut1[g];
        out[i * 3 + 2] = cfg->lut2[g];
    }
}
