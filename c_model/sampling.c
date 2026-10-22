#include <stddef.h>   /* NULL（不依赖编译器/CRT 的间接包含） */

#include "config.h"

/* 模块 1：接口温度值采样
 * 按半字节映射配置把原始字节流重建为 14-bit 温度值，输出行数与源帧
 * 一致（不丢弃最后一行）。可配置屏蔽上下左右边缘的脏数据行/列，
 * 被屏蔽区域用最近的有效行/列数据复制填充。返回输出的温度值个数。 */
uint32_t sampling_run(const uint8_t *stream, uint32_t stream_bytes,
                      const sampling_config_t *cfg, uint16_t *temp14_out) {
    uint32_t need = (uint32_t)cfg->src_height
        * (uint32_t)cfg->bytes_per_pixel * cfg->src_width;
    uint32_t out_count = 0;
    uint16_t stride = (uint16_t)(cfg->src_width + 2);  /* 每行 uint16_t 数（含左右 pad） */
    uint16_t r, c;

    if (stream == NULL || stream_bytes < need) {
        return 0;   /* 字节流尺寸不足 */
    }

    for (r = 0; r < cfg->src_height; r++) {
        /* 边缘脏数据屏蔽：被屏蔽的行用最近的有效行复制 */
        uint16_t src_r = r;
        if (src_r < cfg->skip_top) {
            src_r = cfg->skip_top;
        } else if (src_r >= (uint16_t)(cfg->src_height - cfg->skip_bottom)) {
            src_r = (uint16_t)(cfg->src_height - 1 - cfg->skip_bottom);
        }
        for (c = 0; c < cfg->src_width; c++) {
            /* 被屏蔽的列用最近的有效列复制 */
            uint16_t src_c = c;
            if (src_c < cfg->skip_left) {
                src_c = cfg->skip_left;
            } else if (src_c >= (uint16_t)(cfg->src_width - cfg->skip_right)) {
                src_c = (uint16_t)(cfg->src_width - 1 - cfg->skip_right);
            }
            const uint8_t *p = stream
                + (uint32_t)src_r * (uint32_t)cfg->bytes_per_pixel * cfg->src_width
                + (uint32_t)src_c * cfg->bytes_per_pixel;
            uint16_t v = 0;
            uint8_t i;

            for (i = 0; i < NIBBLE_COUNT; i++) {
                uint8_t src_bit = cfg->shift[i];   /* 源 32 位中的起始位，0-28 */
                uint8_t b = p[src_bit >> 3];       /* 所在字节 */
                uint8_t nib = (uint8_t)((b >> (src_bit & 7u)) & 0x0Fu);
                v |= (uint16_t)((uint16_t)nib << ((NIBBLE_COUNT - 1 - i) * 4));
            }
            temp14_out[(uint32_t)(r + 1) * stride + (c + 1)] = v & ((1 << cfg->value_bits) - 1);
            out_count++;
        }
    }
    return out_count;
}
