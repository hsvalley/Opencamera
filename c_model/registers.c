#include "config.h"

/* 全局寄存器实例（模拟硬件寄存器，跨帧保持，软件通过读写访问） */
regs_t g_regs;

/* 寄存器初始化：计数器清零、trigger 清零、状态正常、无错误 */
void regs_init(regs_t *r) {
    r->raw_frame_cnt = 0;
    r->out_frame_cnt = 0;
    r->cnt_clear = 0;
    r->capture_raw = 0;
    r->capture_out = 0;
    r->status = REG_STATUS_OK;
    r->error_code = REG_ERR_NONE;
}

/* 抓取一帧原始数据：把采样后的 14-bit 帧（含 pad 布局）快照到抓帧缓冲区，
 * 完成后清 trigger（读清语义：抓帧动作即消耗 trigger）。定点、逐字复制。 */
void capture_raw_do(regs_t *r, const uint16_t *src, uint16_t *dst, uint32_t words) {
    uint32_t i;
    for (i = 0; i < words; i++) {
        dst[i] = src[i];
    }
    r->capture_raw = 0;
}

/* 抓取一帧输出图像：把最终 RGB/YUV 交错帧快照到抓帧缓冲区，完成后清 trigger。 */
void capture_out_do(regs_t *r, const uint8_t *src, uint8_t *dst, uint32_t bytes) {
    uint32_t i;
    for (i = 0; i < bytes; i++) {
        dst[i] = src[i];
    }
    r->capture_out = 0;
}
