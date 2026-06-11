#!/usr/bin/env python3
"""
将BIN文件中每两个字节的高4位提取并组合成一个新字节。
输入：原始BIN文件（任意大小，长度为偶数）
输出：新BIN文件（每2字节→1字节），可选转换为8位灰度BMP。
用法：python high4_combine.py input.bin [-o output_dir] [--to-bmp] [--width WIDTH]
"""

import argparse
import os
import glob
import math
import sys

def combine_high4(data):
    """
    每两个字节取高4位组合成新字节。
    data: bytes对象
    返回: bytearray
    """
    if len(data) % 2 != 0:
        raise ValueError("文件长度不是偶数，无法两两组合")
    out = bytearray()
    for i in range(0, len(data), 2):
        b1 = data[i]
        b2 = data[i+1]
        high4_1 = (b1 >> 4) & 0x0F
        high4_2 = (b2 >> 4) & 0x0F
        combined = (high4_1 << 4) | high4_2
        out.append(combined)
    return out

def save_bin(filename, data):
    with open(filename, 'wb') as f:
        f.write(data)

def save_bmp_from_8bit(filename, pixels_8bit, width=None):
    """将8位像素列表保存为灰度BMP"""
    num = len(pixels_8bit)
    if width is None:
        width = int(math.sqrt(num))
        while num % width != 0:
            width -= 1
        if width == 0:
            width = 1
    height = (num + width - 1) // width

    padded = pixels_8bit + [0] * (width * height - num)
    rows = [padded[i*width:(i+1)*width] for i in range(height)]

    row_size = (width + 3) & ~3
    pixel_data_size = row_size * height
    color_table_size = 256 * 4
    file_size = 14 + 40 + color_table_size + pixel_data_size

    with open(filename, 'wb') as f:
        f.write(b'BM')
        f.write(file_size.to_bytes(4, 'little'))
        f.write((0).to_bytes(2, 'little'))
        f.write((0).to_bytes(2, 'little'))
        f.write((14 + 40 + color_table_size).to_bytes(4, 'little'))
        f.write((40).to_bytes(4, 'little'))
        f.write(width.to_bytes(4, 'little'))
        f.write(height.to_bytes(4, 'little'))
        f.write((1).to_bytes(2, 'little'))
        f.write((8).to_bytes(2, 'little'))
        f.write((0).to_bytes(4, 'little'))
        f.write(pixel_data_size.to_bytes(4, 'little'))
        f.write((0).to_bytes(4, 'little'))
        f.write((0).to_bytes(4, 'little'))
        f.write((256).to_bytes(4, 'little'))
        f.write((256).to_bytes(4, 'little'))
        for i in range(256):
            f.write(bytes([i, i, i, 0]))
        for row in reversed(rows):
            f.write(bytes(row))
            f.write(b'\x00' * (row_size - len(row)))

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
    parser = argparse.ArgumentParser(description='提取每两个字节的高4位组合成新字节')
    parser.add_argument('inputs', nargs='+', help='输入文件（支持通配符）')
    parser.add_argument('-o', '--output_dir', default='.', help='输出目录')
    parser.add_argument('--to-bmp', action='store_true', help='同时生成8位灰度BMP')
    parser.add_argument('-w', '--width', type=int, default=None, help='BMP图像宽度（仅当--to-bmp时有效）')
    args = parser.parse_args()

    in_files = expand_paths(args.inputs)
    if not in_files:
        print("未找到任何输入文件")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    for in_file in in_files:
        with open(in_file, 'rb') as f:
            raw = f.read()
        if not raw:
            print(f"空文件: {in_file}")
            continue
        try:
            combined = combine_high4(raw)
        except Exception as e:
            print(f"处理 {in_file} 失败: {e}")
            continue

        base = os.path.splitext(os.path.basename(in_file))[0]
        # 保存BIN
        out_bin = os.path.join(args.output_dir, base + "_high4.bin")
        save_bin(out_bin, combined)
        print(f"已保存: {out_bin} (原大小 {len(raw)} 字节 -> {len(combined)} 字节)")

        if args.to_bmp:
            out_bmp = os.path.join(args.output_dir, base + "_high4.bmp")
            save_bmp_from_8bit(out_bmp, list(combined), args.width)
            num = len(combined)
            if args.width:
                w, h = args.width, (num + args.width - 1) // args.width
            else:
                w = int(math.sqrt(num))
                while num % w != 0:
                    w -= 1
                w = w if w > 0 else 1
                h = (num + w - 1) // w
            print(f"  同时生成BMP: {out_bmp} ({w}x{h})")

if __name__ == '__main__':
    main()