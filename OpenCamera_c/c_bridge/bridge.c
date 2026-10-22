#include "config.h"
#include "bridge.h"

/* 有状态流水线封装：复用 c_model 的模块函数，为 Python(ctypes) 提供
 * 简单稳定的帧级接口。静态缓存模拟硬件 SRAM（固定尺寸，不 malloc），
 * 极值截取状态跨帧保持。 */

static pipeline_config_t g_cfg;                       /* 默认配置 */
static clip_state_t      g_clip_state;                /* 跨帧极值截取状态 */
static uint16_t g_data[(IR_HEIGHT + 2) * IR_STRIDE];  /* 采样/高斯/压缩共用 pad 缓存 */
static uint32_t g_hist[TEMP10_MAX + 1];               /* 直方图统计缓存 */

void bridge_init(void) {
    pipeline_config_default(&g_cfg, COLOR_RGB);
    clip_state_init(&g_clip_state);
}

void bridge_set_clip_mode(int mode) {
    g_cfg.clip.mode = (mode == CLIP_MODE_USER) ? CLIP_MODE_USER : CLIP_MODE_DYNAMIC;
}

void bridge_set_clip_user(uint16_t mn, uint16_t mx) {
    g_cfg.clip.mode = CLIP_MODE_USER;
    g_cfg.clip.user_min = mn;
    g_cfg.clip.user_max = mx;
}

void bridge_set_clip_dynamic(uint8_t n_frames, uint16_t step) {
    g_cfg.clip.mode = CLIP_MODE_DYNAMIC;
    g_cfg.clip.n_frames = n_frames;
    g_cfg.clip.step = step;
}

void bridge_set_hist_reverse(uint8_t reverse) {
    g_cfg.hist_eq.reverse = reverse;
}

void bridge_set_filter_mode(int mode) {
    g_cfg.gaussian.filter_mode = (mode == FILTER_MEDIAN) ? FILTER_MEDIAN : FILTER_GAUSSIAN;
}

void bridge_set_clip_calc_mode(int mode) {
    g_cfg.clip.calc_mode = (mode == CLIP_CALC_LOWPASS) ? CLIP_CALC_LOWPASS : CLIP_CALC_AVG;
    clip_state_init(&g_clip_state);   /* 切换算法时复位跨帧状态 */
}

void bridge_set_lut(const uint8_t *r, const uint8_t *g, const uint8_t *b) {
    int i;
    if (r == NULL || g == NULL || b == NULL) {
        color_config_init(&g_cfg.color, COLOR_RGB);
        return;
    }
    g_cfg.color.format = COLOR_RGB;
    for (i = 0; i < 256; i++) {
        g_cfg.color.lut0[i] = r[i];
        g_cfg.color.lut1[i] = g[i];
        g_cfg.color.lut2[i] = b[i];
    }
}

/* 把采样缓存（stride=width+2 的 pad 布局）紧凑复制到连续输出缓存。 */
static void compact_copy(const uint16_t *src, uint16_t stride,
                         uint16_t width, uint16_t height, uint16_t *dst) {
    uint16_t r, c;
    for (r = 0; r < height; r++) {
        for (c = 0; c < width; c++) {
            dst[(uint32_t)r * width + c] = src[(uint32_t)(r + 1) * stride + (c + 1)];
        }
    }
}

uint32_t bridge_decode(const uint8_t *stream, uint32_t nbytes, uint16_t *temp14_out) {
    uint32_t pixel_count = (uint32_t)g_cfg.sampling.src_width * g_cfg.sampling.src_height;
    uint32_t n = sampling_run(stream, nbytes, &g_cfg.sampling, g_data);
    if (n == pixel_count && temp14_out != NULL) {
        compact_copy(g_data, (uint16_t)(g_cfg.sampling.src_width + 2),
                     g_cfg.sampling.src_width, g_cfg.sampling.src_height, temp14_out);
    }
    return n;
}

int bridge_process(const uint8_t *stream, uint32_t nbytes,
                   const int16_t *calib_map,
                   uint16_t *temp14_out, uint8_t *gray8_out,
                   uint8_t *rgb_out, uint16_t *min_out, uint16_t *max_out) {
    uint16_t width = g_cfg.sampling.src_width;
    uint16_t height = g_cfg.sampling.src_height;
    uint16_t stride = (uint16_t)(width + 2);
    uint32_t pixel_count = (uint32_t)width * height;
    uint16_t min_val, max_val;
    uint16_t r, c;

    if (sampling_run(stream, nbytes, &g_cfg.sampling, g_data) != pixel_count) {
        return -1;
    }

    /* 校准：逐像素减校准误差图，clamp 到 [0, TEMP14_MAX]。 */
    if (calib_map != NULL) {
        for (r = 0; r < height; r++) {
            for (c = 0; c < width; c++) {
                uint32_t idx = (uint32_t)(r + 1) * stride + (c + 1);
                int32_t v = (int32_t)g_data[idx] - (int32_t)calib_map[(uint32_t)r * width + c];
                if (v < 0) v = 0;
                if (v > TEMP14_MAX) v = TEMP14_MAX;
                g_data[idx] = (uint16_t)v;
            }
        }
    }

    /* 校准后、高斯前的 14-bit 输出（可选）。 */
    if (temp14_out != NULL) {
        compact_copy(g_data, stride, width, height, temp14_out);
    }

    /* 滤波 -> 极值截取 -> 线性压缩 -> 直方图均衡 -> 查表。 */
    filter_run(g_data, width, height, g_cfg.sampling.value_bits, stride, &g_cfg.gaussian);
    clip_extremes(g_data, pixel_count, &g_cfg.clip, &g_clip_state, &min_val, &max_val);
    compress_run(g_data, pixel_count, min_val, max_val, &g_cfg.compress);
    hist_eq_run(g_data, pixel_count, &g_cfg.hist_eq, g_hist, gray8_out);
    color_run(gray8_out, pixel_count, &g_cfg.color, rgb_out);

    if (min_out != NULL) *min_out = min_val;
    if (max_out != NULL) *max_out = max_val;
    return 0;
}
