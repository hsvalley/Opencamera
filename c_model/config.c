#include "config.h"

/* 默认配置初始化：各项参数均以数据结构描述，便于替换/裁剪。 */
void pipeline_config_default(pipeline_config_t *cfg, color_format_t format) {
    sampling_config_t *s = &cfg->sampling;
    gaussian_config_t *g = &cfg->gaussian;
    static const int16_t gauss_kernel[9] = {1, 2, 1, 2, 4, 2, 1, 2, 1};
    int i;

    /* 模块 1：采样默认映射
     * 取各字节高 4 位（源位 4/12/20/28），第 0 个半字节最高位，
     * 等价于 b0_hi<<12 | b1_hi<<8 | b2_hi<<4 | b3_hi。 */
    s->shift[0] = 4;  s->shift[1] = 12;
    s->shift[2] = 20; s->shift[3] = 28;
    s->bytes_per_pixel = 4;
    s->value_bits = TEMP14_BITS;
    s->src_width = IR_WIDTH;
    s->src_height = IR_HEIGHT;   /* 输出行数 = 源行数，不丢弃最后一行 */
    s->skip_top = 0;             /* 边缘脏数据屏蔽，默认关闭 */
    s->skip_bottom = 0;
    s->skip_left = 0;
    s->skip_right = 0;

    /* 模块 2：滤波默认高斯，权重 [1 2 1; 2 4 2; 1 2 1]，归一化 16 */
    g->filter_mode = FILTER_GAUSSIAN;
    for (i = 0; i < 9; i++) {
        g->kernel[i] = gauss_kernel[i];
    }
    g->norm = 16;

    /* 模块 3：极值截取默认动态统计，低通方式，N=4，step=16 */
    cfg->clip.mode = CLIP_MODE_DYNAMIC;
    cfg->clip.calc_mode = CLIP_CALC_LOWPASS;
    cfg->clip.user_min = 0;
    cfg->clip.user_max = TEMP14_MAX;
    cfg->clip.n_frames = 4;
    cfg->clip.step = 16;

    /* 模块 4：线性压缩到 10-bit */
    cfg->compress.out_bits = TEMP10_BITS;
    cfg->compress.out_max = TEMP10_MAX;

    /* 模块 5：直方图均衡到 8-bit */
    cfg->hist_eq.out_bits = 8;
    cfg->hist_eq.reverse = 1;   /* 默认反相：灰度降序（高温=暗） */

    /* 模块 6：查表（含 LUT 生成） */
    color_config_init(&cfg->color, format);
}
