#!/usr/bin/env python3
"""
14位红外BIN转BMP，采用裁剪线性拉伸 + 可选的中值滤波，避免噪声放大和断层。
大端序（高位在前），每像素2字节，低14位有效。
用法：python ir14_clip.py input.bin -w WIDTH [--clip 0.01] [--median 3] [--gray]
"""

import argparse
import os
import math
import sys

def read_14bit_be(filename):
    with open(filename, 'rb') as f:
        data = f.read()
    if len(data) % 2 != 0:
        raise ValueError("文件大小不是偶数")
    pixels = []
    for i in range(0, len(data), 2):
        val = (data[i] << 8) | data[i+1]
        pixels.append(val & 0x3FFF)
    return pixels

def median_filter_1d(data, width, height, kernel=3):
    """对一维列表表示的图像进行二维中值滤波（纯Python）"""
    pad = kernel // 2
    # 转为二维列表便于处理
    img = [data[i*width:(i+1)*width] for i in range(height)]
    result = [[0]*width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            neighbors = []
            for dy in range(-pad, pad+1):
                for dx in range(-pad, pad+1):
                    ny, nx = y+dy, x+dx
                    if 0 <= ny < height and 0 <= nx < width:
                        neighbors.append(img[ny][nx])
            neighbors.sort()
            result[y][x] = neighbors[len(neighbors)//2]
    return [p for row in result for p in row]

def clip_linear_stretch(pixels, clip_ratio=0.01, min_val=None, max_val=None):
    """
    裁剪线性拉伸：去掉低端和高端各 clip_ratio 比例，然后线性映射到 0-255。
    如果提供了 min_val 和 max_val，则直接使用它们（不自动裁剪）。
    """
    if min_val is not None and max_val is not None:
        lo, hi = min_val, max_val
    else:
        n = len(pixels)
        sorted_pixels = sorted(pixels)
        lo = sorted_pixels[int(n * clip_ratio)]
        hi = sorted_pixels[int(n * (1 - clip_ratio))]
        if lo == hi:
            lo = min(pixels)
            hi = max(pixels)
    # 线性映射到 0-255
    mapped = []
    for p in pixels:
        if p <= lo:
            mapped.append(0)
        elif p >= hi:
            mapped.append(255)
        else:
            mapped.append(int((p - lo) / (hi - lo) * 255))
    return mapped

def gray_to_pseudo(gray):
    if gray < 64:
        return (0, 0, gray*4)
    elif gray < 128:
        g = (gray-64)*4
        return (g, 0, 255 - g)
    elif gray < 192:
        g = (gray-128)*4
        return (255, g, 0)
    else:
        g = (gray-192)*4
        return (255, 255, g)

def write_bmp(filename, gray_vals, width, height, pseudo=False):
    """gray_vals: 0-255 列表"""
    num = width * height
    if len(gray_vals) < num:
        gray_vals = gray_vals + [0]*(num - len(gray_vals))
    # 构建 RGB 数据
    rgb = bytearray()
    for g in gray_vals[:num]:
        if pseudo:
            r,g,b = gray_to_pseudo(g)
        else:
            r = g = b = g
        rgb.extend([r,g,b])
    # BMP 24位
    row_bytes = width * 3
    padding = (4 - row_bytes % 4) % 4
    row_stride = row_bytes + padding
    pixel_data_size = row_stride * height
    file_size = 14 + 40 + pixel_data_size
    with open(filename, 'wb') as f:
        f.write(b'BM')
        f.write(file_size.to_bytes(4, 'little'))
        f.write((0).to_bytes(2, 'little'))
        f.write((0).to_bytes(2, 'little'))
        f.write((14+40).to_bytes(4, 'little'))
        f.write((40).to_bytes(4, 'little'))
        f.write(width.to_bytes(4, 'little'))
        f.write(height.to_bytes(4, 'little'))
        f.write((1).to_bytes(2, 'little'))
        f.write((24).to_bytes(2, 'little'))
        f.write((0).to_bytes(4, 'little'))
        f.write(pixel_data_size.to_bytes(4, 'little'))
        f.write((0).to_bytes(4, 'little'))
        f.write((0).to_bytes(4, 'little'))
        f.write((0).to_bytes(4, 'little'))
        f.write((0).to_bytes(4, 'little'))
        for y in range(height-1, -1, -1):
            row_start = y * width * 3
            row = rgb[row_start:row_start+width*3]
            for i in range(0, len(row), 3):
                f.write(bytes([row[i+2], row[i+1], row[i]]))
            f.write(b'\x00' * padding)

def main():
    parser = argparse.ArgumentParser(description='红外BIN转BMP（裁剪拉伸+可选滤波）')
    parser.add_argument('input', help='输入BIN文件')
    parser.add_argument('-w', '--width', type=int, required=True, help='图像宽度')
    parser.add_argument('-o', '--output', default=None, help='输出BMP路径')
    parser.add_argument('--gray', action='store_true', help='灰度模式（默认伪彩色）')
    parser.add_argument('--clip', type=float, default=0.005, help='裁剪比例，例如0.005表示去除两端0.5%%异常值')
    parser.add_argument('--min', type=int, default=None, help='手动指定最小值（覆盖自动裁剪）')
    parser.add_argument('--max', type=int, default=None, help='手动指定最大值')
    parser.add_argument('--median', type=int, default=0, help='中值滤波核大小（奇数，如3），0表示不滤波')
    args = parser.parse_args()

    pixels = read_14bit_be(args.input)
    total = len(pixels)
    height = total // args.width
    if total % args.width != 0:
        print(f"警告: 数据像素数({total})不是宽度({args.width})的整数倍，将截断")
        height = total // args.width
        pixels = pixels[:args.width*height]
    print(f"原始数据范围: [{min(pixels)}, {max(pixels)}]")

    # 中值滤波
    if args.median > 0:
        if args.median % 2 == 0:
            print("中值滤波核必须为奇数，自动加1")
            args.median += 1
        print(f"应用 {args.median}x{args.median} 中值滤波...")
        pixels = median_filter_1d(pixels, args.width, height, args.median)

    # 裁剪拉伸
    gray_vals = clip_linear_stretch(pixels, args.clip, args.min, args.max)

    # 输出路径
    if args.output is None:
        base = os.path.splitext(args.input)[0]
        suffix = "_gray" if args.gray else "_pseudo"
        if args.clip > 0:
            suffix += f"_clip{int(args.clip*1000)}"
        if args.median > 0:
            suffix += f"_med{args.median}"
        out = f"{base}{suffix}.bmp"
    else:
        out = args.output

    write_bmp(out, gray_vals, args.width, height, pseudo=not args.gray)
    print(f"已保存: {out} ({args.width}x{height})")

if __name__ == '__main__':
    main()