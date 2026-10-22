#ifndef C_MODEL_BRIDGE_H
#define C_MODEL_BRIDGE_H

#include <stdint.h>

#if defined(_WIN32) || defined(_WIN64)
#define BRIDGE_API __declspec(dllexport)
#else
#define BRIDGE_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* 初始化：加载默认配置，复位极值截取跨帧状态。 */
BRIDGE_API void bridge_init(void);

/* 极值截取模块配置。 */
BRIDGE_API void bridge_set_clip_mode(int mode);                 /* 0=USER, 1=DYNAMIC */
BRIDGE_API void bridge_set_clip_user(uint16_t mn, uint16_t mx);
BRIDGE_API void bridge_set_clip_dynamic(uint8_t n_frames, uint16_t step);
BRIDGE_API void bridge_set_clip_calc_mode(int mode);            /* 0=滑动窗口平均, 1=低通 */
BRIDGE_API void bridge_set_hist_reverse(uint8_t reverse);      /* 0:升序, 1:反相 */

/* 滤波模块配置。 */
BRIDGE_API void bridge_set_filter_mode(int mode);              /* 0=高斯, 1=中值 */

/* 自定义伪彩 LUT（各 256 项；任一为 NULL 则恢复内置 LUT）。 */
BRIDGE_API void bridge_set_lut(const uint8_t *r, const uint8_t *g, const uint8_t *b);

/* 模块 1 采样：原始字节流 -> 紧凑 14-bit（IR_WIDTH x IR_HEIGHT）。返回像素数。 */
BRIDGE_API uint32_t bridge_decode(const uint8_t *stream, uint32_t nbytes,
                                  uint16_t *temp14_out);

/* 完整流水线：采样 -> 校准(可选) -> 滤波(高斯/中值) -> 极值截取 -> 线性压缩 -> 直方图均衡 -> 查表。
 * calib_map: NULL 或 IR_WIDTH*IR_HEIGHT 个 int16 校准误差图。
 * 输出: temp14_out(校准后高斯前，可 NULL)、gray8_out、rgb_out(交错 RGB)、min_out/max_out。
 * 返回 0 成功，非 0 失败。 */
BRIDGE_API int bridge_process(const uint8_t *stream, uint32_t nbytes,
                              const int16_t *calib_map,
                              uint16_t *temp14_out, uint8_t *gray8_out,
                              uint8_t *rgb_out, uint16_t *min_out, uint16_t *max_out);

#ifdef __cplusplus
}
#endif

#endif /* C_MODEL_BRIDGE_H */
