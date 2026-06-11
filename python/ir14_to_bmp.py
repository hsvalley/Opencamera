#!/usr/bin/env python3
"""
将14位红外BIN文件（大端序，每像素2字节，高位在前）转换为BMP图片。
支持灰度或铁红伪彩色，可手动指定温度范围（最小/最大值）。
用法：python ir14_to_bmp.py input.bin [-w WIDTH] [--gray] [--min MIN] [--max MAX]
"""

import argparse
import os
import math
import glob
import sys

def read_14bit_be(filename):
    """读取大端序14位数据，每2字节组合，保留低14位，返回像素列表"""
    with open(filename, 'rb') as f:
        data = f.read()
    if len(data) % 2 != 0:
        raise ValueError(f"{filename} 大小不是偶数")
    pixels = []
    for i in range(0, len(data), 2):
        # 大端序：第一个字节是高位，第二个是低位
        val = (data[i] << 8) | data[i+1]
        pixels.append(val & 0x3FFF)  # 保留低14位
    return pixels

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

def write_bmp(filename, pixels_14bit, width=None, gray_mode=True, min_val=None, max_val=None):
    num = len(pixels_14bit)
    if width is None:
        width = int(math.sqrt(num))
        while num % width != 0:
            width -= 1
        if width == 0:
            width = 1
    height = (num + width - 1) // width

    # 动态范围：未指定则使用实际最小值/最大值
    if min_val is None:
        min_val = min(pixels_14bit)
    if max_val is None:
        max_val = max(pixels_14bit)
    if max_val == min_val:
        max_val = min_val + 1

    # 归一化到 0-255
    rgb_data = bytearray()
    for p in pixels_14bit:
        # 钳位到 [min, max]
        p_clamped = max(min(p, max_val), min_val)
        gray = int((p_clamped - min_val) / (max_val - min_val) * 255)
        gray = max(0, min(255, gray))
        if gray_mode:
            r = g = b = gray
        else:
            r, g, b = gray_to_pseudo(gray)
        rgb_data.extend([r, g, b])

    # 填充最后一行不足像素
    pad_pixels = width * height - num
    rgb_data.extend([0, 0, 0] * pad_pixels)

    # BMP 24位参数
    row_bytes = width * 3
    padding = (4 - row_bytes % 4) % 4
    row_stride = row_bytes + padding
    pixel_data_size = row_stride * height
    file_size = 14 + 40 + pixel_data_size

    with open(filename, 'wb') as f:
        # 文件头
        f.write(b'BM')
        f.write(file_size.to_bytes(4, 'little'))
        f.write((0).to_bytes(2, 'little'))
        f.write((0).to_bytes(2, 'little'))
        f.write((14 + 40).to_bytes(4, 'little'))
        # 信息头
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
        # 像素数据（自底向上，BGR顺序）
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
    parser = argparse.ArgumentParser(description='14位红外BIN（大端序）转灰度/伪彩色BMP')
    parser.add_argument('inputs', nargs='+', help='输入BIN文件（支持通配符）')
    parser.add_argument('-w', '--width', type=int, default=None, help='图像宽度，不指定则自动计算')
    parser.add_argument('-o', '--output_dir', default='.', help='输出目录')
    parser.add_argument('--gray', action='store_true', help='输出灰度图（默认伪彩色）')
    parser.add_argument('--min', type=int, default=6616, help='温度范围最小值（默认6616）')
    parser.add_argument('--max', type=int, default=10502, help='温度范围最大值（默认10502）')
    parser.add_argument('--auto-range', action='store_true', help='自动使用数据的实际最小值/最大值，忽略--min/--max')
    args = parser.parse_args()

    in_files = expand_paths(args.inputs)
    if not in_files:
        print("未找到任何输入文件")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    for in_file in in_files:
        try:
            pixels = read_14bit_be(in_file)
            print(f"读取 {in_file}: {len(pixels)} 个像素, 实际范围 [{min(pixels)}, {max(pixels)}]")
        except Exception as e:
            print(f"读取失败 {in_file}: {e}")
            continue

        # 决定使用的min/max
        if args.auto_range:
            min_val = min(pixels)
            max_val = max(pixels)
        else:
            min_val = args.min
            max_val = args.max

        # 输出文件名
        base = os.path.splitext(os.path.basename(in_file))[0]
        suffix = "_gray" if args.gray else "_pseudo"
        out_bmp = os.path.join(args.output_dir, base + suffix + ".bmp")
        write_bmp(out_bmp, pixels, args.width, gray_mode=args.gray,
                  min_val=min_val, max_val=max_val)

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
        print(f"已保存: {out_bmp} ({w}x{h}), 动态范围 [{min_val}, {max_val}]")

if __name__ == '__main__':
    main()