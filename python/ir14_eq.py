#!/usr/bin/env python3
"""
将14位红外BIN文件（大端序，每像素2字节）转换为BMP图片。
支持灰度/伪彩色，支持直方图均衡化增强对比度。
用法：python ir14_eq.py input.bin -w WIDTH [--gray] [--equalize] [--min MIN] [--max MAX]
"""

import argparse
import os
import math
import glob
import sys

def read_14bit_be(filename):
    """读取大端序14位数据，返回像素列表（0-16383）"""
    with open(filename, 'rb') as f:
        data = f.read()
    if len(data) % 2 != 0:
        raise ValueError(f"{filename} 大小不是偶数")
    pixels = []
    for i in range(0, len(data), 2):
        val = (data[i] << 8) | data[i+1]
        pixels.append(val & 0x3FFF)
    return pixels

def hist_equalize(pixels_14bit, min_val, max_val):
    """
    对14位数据进行全局直方图均衡化，拉伸到[min_val, max_val]范围。
    输入像素值范围0-16383，输出均衡化后的像素值（仍在0-16383区间）。
    """
    # 统计直方图（0-16383）
    hist = [0] * 16384
    for p in pixels_14bit:
        hist[p] += 1
    # 累积分布函数（CDF）
    cdf = [0] * 16384
    total = len(pixels_14bit)
    cum = 0
    for i in range(16384):
        cum += hist[i]
        cdf[i] = cum / total
    # 映射：cdf最小值对应的输出为min_val，最大值对应max_val
    # 找到cdf最小值不为0的索引
    min_cdf = None
    max_cdf = None
    for i in range(16384):
        if cdf[i] > 0:
            if min_cdf is None:
                min_cdf = cdf[i]
            max_cdf = cdf[i]
    if min_cdf is None:
        return pixels_14bit  # 无有效数据
    # 映射公式
    def map_func(p):
        if p < 0 or p >= 16384:
            return min_val
        c = cdf[p]
        # 线性拉伸
        out = min_val + (max_val - min_val) * (c - min_cdf) / (max_cdf - min_cdf)
        return int(round(out))
    return [map_func(p) for p in pixels_14bit]

def gray_to_pseudo(gray):
    """铁红风格伪彩色映射：gray 0-255 -> (r,g,b)"""
    if gray < 64:
        r, g, b = 0, 0, gray * 4
    elif gray < 128:
        r, g, b = (gray - 64) * 4, 0, 255 - (gray - 64) * 4
    elif gray < 192:
        r, g, b = 255, (gray - 128) * 4, 0
    else:
        r, g, b = 255, 255, (gray - 192) * 4
    return r, g, b

def write_bmp(filename, pixels_14bit, width=None, gray_mode=False, 
              min_val=None, max_val=None, do_equalize=False):
    num = len(pixels_14bit)
    if width is None:
        width = int(math.sqrt(num))
        while num % width != 0:
            width -= 1
        if width == 0:
            width = 1
    height = (num + width - 1) // width

    # 动态范围：未指定则使用实际min/max
    if min_val is None:
        min_val = min(pixels_14bit)
    if max_val is None:
        max_val = max(pixels_14bit)
    if max_val == min_val:
        max_val = min_val + 1

    # 直方图均衡化（在14位空间进行，然后拉伸到[min_val, max_val]）
    if do_equalize:
        pixels_eq = hist_equalize(pixels_14bit, min_val, max_val)
    else:
        # 直接钳位并归一化
        pixels_eq = [max(min(p, max_val), min_val) for p in pixels_14bit]

    # 归一化到0-255
    range_val = max_val - min_val
    if range_val == 0:
        range_val = 1
    rgb_data = bytearray()
    for p in pixels_eq:
        # 确保p在[min_val, max_val]内（均衡化已保证）
        gray = int((p - min_val) / range_val * 255)
        gray = max(0, min(255, gray))
        if gray_mode:
            r = g = b = gray
        else:
            r, g, b = gray_to_pseudo(gray)
        rgb_data.extend([r, g, b])

    # 填充最后一行
    pad_pixels = width * height - num
    rgb_data.extend([0, 0, 0] * pad_pixels)

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
        f.write((14 + 40).to_bytes(4, 'little'))
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
        for y in range(height - 1, -1, -1):
            row_start = y * width * 3
            row = rgb_data[row_start:row_start + width*3]
            for i in range(0, len(row), 3):
                f.write(bytes([row[i+2], row[i+1], row[i]]))
            f.write(b'\x00' * padding)

def expand_paths(patterns):
    files = []
    for p in patterns:
        if '*' in p or '?' in p:
            files.extend(glob.glob(p))
        elif os.path.exists(p):
            files.append(p)
        else:
            print(f"警告: 文件不存在 {p}")
    return files

def main():
    parser = argparse.ArgumentParser(description='14位红外BIN转BMP，支持直方图均衡化')
    parser.add_argument('inputs', nargs='+', help='输入BIN文件（支持通配符）')
    parser.add_argument('-w', '--width', type=int, default=None, help='图像宽度')
    parser.add_argument('-o', '--output_dir', default='.', help='输出目录')
    parser.add_argument('--gray', action='store_true', help='灰度模式（默认伪彩色）')
    parser.add_argument('--min', type=int, default=6616, help='温度范围最小值（默认6616）')
    parser.add_argument('--max', type=int, default=10502, help='温度范围最大值（默认10502）')
    parser.add_argument('--auto-range', action='store_true', help='自动使用数据的实际min/max')
    parser.add_argument('--equalize', action='store_true', help='使用直方图均衡化增强对比度')
    args = parser.parse_args()

    in_files = expand_paths(args.inputs)
    if not in_files:
        print("未找到任何输入文件")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    for in_file in in_files:
        try:
            pixels = read_14bit_be(in_file)
            print(f"读取 {in_file}: {len(pixels)} 像素, 原始范围 [{min(pixels)}, {max(pixels)}]")
        except Exception as e:
            print(f"读取失败 {in_file}: {e}")
            continue

        if args.auto_range:
            min_val = min(pixels)
            max_val = max(pixels)
        else:
            min_val = args.min
            max_val = args.max

        # 生成输出文件名
        base = os.path.splitext(os.path.basename(in_file))[0]
        suffix = "_gray" if args.gray else "_pseudo"
        if args.equalize:
            suffix += "_eq"
        out_bmp = os.path.join(args.output_dir, base + suffix + ".bmp")

        write_bmp(out_bmp, pixels, args.width, gray_mode=args.gray,
                  min_val=min_val, max_val=max_val, do_equalize=args.equalize)

        # 显示尺寸
        num = len(pixels)
        if args.width:
            w, h = args.width, (num + args.width - 1) // args.width
        else:
            w = int(math.sqrt(num))
            while num % w != 0:
                w -= 1
            w = w if w > 0 else 1
            h = (num + w - 1) // w
        print(f"已保存: {out_bmp} ({w}x{h}), 动态范围 [{min_val}, {max_val}], 均衡化: {args.equalize}")

if __name__ == '__main__':
    main()