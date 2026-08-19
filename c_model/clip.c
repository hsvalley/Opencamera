#include "config.h"

/* 模块 3 状态初始化：当前极值取全范围，窗口清空 */
void clip_state_init(clip_state_t *st) {
#if CLIP_USE_LOWPASS == 0
    uint8_t i;
    for (i = 0; i < CLIP_MAX_FRAMES; i++) {
        st->min_buf[i] = 0;
        st->max_buf[i] = TEMP14_MAX;
    }
    st->sum_min = 0;
    st->sum_max = 0;
    st->write_idx = 0;
#endif
    st->cnt = 0;
    st->cur_min = 0;
    st->cur_max = TEMP14_MAX;
}

/* 模块 3：极值截取（多帧平均平滑）
 * USER 模式直接返回用户配置的 min/max；
 * DYNAMIC 模式每帧统计简单 min/max，维护 N 帧滑动窗口，用窗口内极值
 * 的平均值更新当前极值。更新条件为变化量 >= step（滞回），满足则直接
 * 设为平均值。未满 N 帧前用已累积帧的平均值。 */
void clip_extremes(const uint16_t *img, uint32_t count,
                   const clip_config_t *cfg, clip_state_t *st,
                   uint16_t *min_out, uint16_t *max_out) {
    uint32_t i;
    uint16_t frame_min, frame_max;
#if CLIP_USE_LOWPASS == 0
    uint32_t n = cfg->n_frames;
    uint16_t avg_min, avg_max;
    int32_t diff_min, diff_max;
#endif

    if (cfg->mode == CLIP_MODE_USER) {
        *min_out = cfg->user_min;
        *max_out = cfg->user_max;
        return;
    }

    if (count == 0) {
        *min_out = st->cur_min;
        *max_out = st->cur_max;
        return;
    }

    /* 1. 统计本帧简单 min/max */
    frame_min = img[0];
    frame_max = img[0];
    for (i = 1; i < count; i++) {
        if (img[i] < frame_min) frame_min = img[i];
        if (img[i] > frame_max) frame_max = img[i];
    }

#if CLIP_USE_LOWPASS == 0
    /* 2. 写入滑动窗口（环形），维护累积和 */
    if (n == 0) n = 1;                       /* 保护 */
    if (n > CLIP_MAX_FRAMES) n = CLIP_MAX_FRAMES;

    if (st->cnt < n) {
        /* 未满：顺序写入，累加 */
        st->min_buf[st->cnt] = frame_min;
        st->max_buf[st->cnt] = frame_max;
        st->sum_min += frame_min;
        st->sum_max += frame_max;
        st->cnt++;
    } else {
        /* 已满：覆盖最旧（write_idx），先减旧再加新 */
        st->sum_min -= st->min_buf[st->write_idx];
        st->sum_max -= st->max_buf[st->write_idx];
        st->min_buf[st->write_idx] = frame_min;
        st->max_buf[st->write_idx] = frame_max;
        st->sum_min += frame_min;
        st->sum_max += frame_max;
        st->write_idx = (uint8_t)((st->write_idx + 1u) % n);
    }

    /* 3. 窗口平均值（已累积 cnt 帧） */
    avg_min = (uint16_t)(st->sum_min / st->cnt);
    avg_max = (uint16_t)(st->sum_max / st->cnt);

    /* 4. 变化量 >= step 才更新（直接设为平均值） */
    diff_min = (int32_t)avg_min - (int32_t)st->cur_min;
    diff_max = (int32_t)avg_max - (int32_t)st->cur_max;
    if (diff_min >= (int32_t)cfg->step || diff_min <= -(int32_t)cfg->step) {
        st->cur_min = avg_min;
    }
    if (diff_max >= (int32_t)cfg->step || diff_max <= -(int32_t)cfg->step) {
        st->cur_max = avg_max;
    }
#else
//采用低通滤波方式
    if (st->cnt == 0) {
        st->cur_min = frame_min;
        st->cur_max = frame_max;
    } else {
        st->cur_min = (uint16_t)((st->cur_min * (cfg->n_frames - 1) + frame_min) / cfg->n_frames);
        st->cur_max = (uint16_t)((st->cur_max * (cfg->n_frames - 1) + frame_max) / cfg->n_frames);
    }
    st->cnt++;
#endif

    *min_out = st->cur_min;
    *max_out = st->cur_max;
}
