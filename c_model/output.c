#include <stdio.h>

#include "config.h"

/* 小端写辅助（不依赖 string.h） */
static void put_u16_le(uint8_t *p, uint16_t v) {
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)((v >> 8) & 0xFFu);
}

static void put_u32_le(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v & 0xFFu);
    p[1] = (uint8_t)((v >> 8) & 0xFFu);
    p[2] = (uint8_t)((v >> 16) & 0xFFu);
    p[3] = (uint8_t)((v >> 24) & 0xFFu);
}

/* 写 24-bit BMP（自底向上，BGR 顺序，行 4 字节对齐） */
int bmp_write(const char *path, const uint8_t *rgb,
              uint16_t width, uint16_t height) {
    FILE *f;
    uint8_t header[54];
    uint32_t row_bytes = (uint32_t)width * 3u;
    uint32_t padding = (4u - (row_bytes % 4u)) % 4u;
    uint32_t row_stride = row_bytes + padding;
    uint32_t pixel_data_size = row_stride * (uint32_t)height;
    uint32_t file_size = 54u + pixel_data_size;
    static const uint8_t pad[3] = {0, 0, 0};
    uint32_t i;
    int y;

    f = fopen(path, "wb");
    if (f == NULL) {
        return -1;
    }

    for (i = 0; i < 54u; i++) {
        header[i] = 0;
    }
    header[0] = 'B';
    header[1] = 'M';
    put_u32_le(header + 2, file_size);
    put_u32_le(header + 10, 54u);                 /* 像素数据偏移 */
    put_u32_le(header + 14, 40u);                 /* BITMAPINFOHEADER 大小 */
    put_u32_le(header + 18, (uint32_t)width);
    put_u32_le(header + 22, (uint32_t)height);
    put_u16_le(header + 26, 1u);                  /* planes */
    put_u16_le(header + 28, 24u);                 /* bpp */
    put_u32_le(header + 34, pixel_data_size);     /* 图像数据大小 */

    fwrite(header, 1, 54, f);

    for (y = (int)height - 1; y >= 0; y--) {
        const uint8_t *row = rgb + (uint32_t)y * row_bytes;
        for (i = 0; i < (uint32_t)width; i++) {
            uint8_t bgr[3];
            bgr[0] = row[i * 3u + 2u];   /* B */
            bgr[1] = row[i * 3u + 1u];   /* G */
            bgr[2] = row[i * 3u + 0u];   /* R */
            fwrite(bgr, 1, 3, f);
        }
        if (padding != 0) {
            fwrite(pad, 1, padding, f);
        }
    }

    fclose(f);
    return 0;
}

/* 写 YUV444 平面文件（Y 全尺寸 + U 全尺寸 + V 全尺寸） */
int yuv_write(const char *path, const uint8_t *yuv444,
              uint16_t width, uint16_t height) {
    FILE *f;
    uint32_t plane = (uint32_t)width * (uint32_t)height;
    static uint8_t plane_buf[PIXEL_COUNT];   /* 52260 字节 */
    uint32_t i;

    if (plane > PIXEL_COUNT) {
        return -1;
    }

    f = fopen(path, "wb");
    if (f == NULL) {
        return -1;
    }

    for (i = 0; i < plane; i++) {
        plane_buf[i] = yuv444[i * 3u + 0u];
    }
    fwrite(plane_buf, 1, plane, f);

    for (i = 0; i < plane; i++) {
        plane_buf[i] = yuv444[i * 3u + 1u];
    }
    fwrite(plane_buf, 1, plane, f);

    for (i = 0; i < plane; i++) {
        plane_buf[i] = yuv444[i * 3u + 2u];
    }
    fwrite(plane_buf, 1, plane, f);

    fclose(f);
    return 0;
}
