from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from infrared_player.infrared import (  # noqa: E402
    IR_HEIGHT,
    IR_UVC_WIDTH,
    IR_WIDTH,
    RAW_IR_HEIGHT,
    InfraredProcessor,
    _apply_calibration,
    _build_calibration_grid,
    _interpolate_calibration_grid,
    clip_linear_stretch,
    compute_ooc,
    decode_infrared_payload,
    gray_to_pseudo,
    load_calibration_grid_bin,
    median_filter,
    pack_ooc_bytes,
    save_calibration_grid_bin,
    save_ooc_txt,
)


class InfraredPipelineTests(unittest.TestCase):
    def test_decode_sample_payload_has_expected_shape(self) -> None:
        raw = (ROOT / "data" / "1.bin").read_bytes()
        frame = np.frombuffer(raw, dtype=np.uint8).reshape(RAW_IR_HEIGHT, IR_UVC_WIDTH, 2)
        decoded = decode_infrared_payload(frame)
        self.assertEqual(decoded.shape, (IR_HEIGHT, IR_WIDTH))
        self.assertEqual(decoded.dtype, np.uint16)
        self.assertGreaterEqual(int(decoded.min()), 0)
        self.assertLessEqual(int(decoded.max()), 0x3FFF)

    def test_decode_first_pixels_match_manual_reference(self) -> None:
        raw = np.frombuffer((ROOT / "data" / "1.bin").read_bytes(), dtype=np.uint8)
        frame = raw.reshape(RAW_IR_HEIGHT, IR_UVC_WIDTH, 2)
        decoded = decode_infrared_payload(frame)

        expected = []
        for offset in range(0, 12, 4):
            b0, b1, b2, b3 = (int(raw[offset + i]) for i in range(4))
            value16 = ((b0 >> 4) << 12) | ((b1 >> 4) << 8) | ((b2 >> 4) << 4) | (b3 >> 4)
            expected.append(value16 & 0x3FFF)
        np.testing.assert_array_equal(decoded[0, :3], np.array(expected, dtype=np.uint16))

    def test_processing_outputs_gray_and_pseudo_images(self) -> None:
        raw = (ROOT / "data" / "1.bin").read_bytes()
        frame = np.frombuffer(raw, dtype=np.uint8).reshape(RAW_IR_HEIGHT, IR_UVC_WIDTH, 2)
        infrared = InfraredProcessor().process(frame)

        self.assertEqual(infrared.gray8.shape, (IR_HEIGHT, IR_WIDTH))
        self.assertEqual(infrared.gray8.dtype, np.uint8)
        self.assertEqual(infrared.pseudo_rgb.shape, (IR_HEIGHT, IR_WIDTH, 3))
        self.assertEqual(infrared.pseudo_rgb.dtype, np.uint8)

    def test_clip_stretch_and_pseudo_color_preserve_shape(self) -> None:
        temp14 = np.arange(IR_HEIGHT * IR_WIDTH, dtype=np.uint16).reshape(IR_HEIGHT, IR_WIDTH) % 16384
        gray8 = clip_linear_stretch(temp14)
        filtered = median_filter(gray8, kernel_size=3)
        pseudo = gray_to_pseudo(filtered)

        self.assertEqual(gray8.shape, temp14.shape)
        self.assertEqual(filtered.shape, temp14.shape)
        self.assertEqual(pseudo.shape, (*temp14.shape, 3))

    def test_clip_stretch_uses_full_data_range(self) -> None:
        """直方图均衡基于数据自身的 min/max，不做外部截断。"""
        temp14 = np.array(
            [
                [7606, 7616, 8559],
                [9502, 9512, 7617],
            ],
            dtype=np.uint16,
        )

        gray8 = clip_linear_stretch(temp14)

        # 数据 min=7606 → 0，max=9512 → 255，中间均匀分布
        self.assertEqual(int(gray8[0, 0]), 0)
        self.assertEqual(int(gray8[1, 1]), 255)
        self.assertTrue(0 < int(gray8[0, 1]) < 128)
        self.assertTrue(128 < int(gray8[1, 0]) < 255)

    def test_decode_keeps_last_raw_row(self) -> None:
        raw_rows = np.zeros((RAW_IR_HEIGHT, IR_WIDTH, 4), dtype=np.uint8)
        raw_rows[-1, :, :] = 0xF0
        frame = raw_rows.reshape(RAW_IR_HEIGHT, IR_UVC_WIDTH, 2)

        decoded = decode_infrared_payload(frame)

        self.assertEqual(decoded.shape, (RAW_IR_HEIGHT, IR_WIDTH))
        self.assertEqual(int(decoded[-1, 0]), 0x3FFF)

    def test_compute_ooc_formula_and_clamping(self) -> None:
        temp14 = np.array([12000, 11300, 12700, 0, 16383], dtype=np.uint16)
        ooc = compute_ooc(temp14)
        np.testing.assert_array_equal(ooc, np.array([7, 8, 6, 15, 1], dtype=np.uint8))

    def test_pack_ooc_bytes_even_high_odd_low(self) -> None:
        ooc = np.array([7, 8, 6, 7], dtype=np.uint8)
        packed = pack_ooc_bytes(ooc)
        np.testing.assert_array_equal(packed, np.array([0x78, 0x67], dtype=np.uint8))

    def test_save_ooc_txt_writes_hex_bytes(self) -> None:
        temp14 = np.array([12000, 11300, 12700, 12000], dtype=np.uint16)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ooc_test.txt"
            save_ooc_txt(temp14, path)
            self.assertEqual(path.read_text(encoding="ascii"), "0x78, 0x67")

    def test_calibration_grid_shape_and_memory_saving(self) -> None:
        """网格只保存 n×n 正方形的 4 个顶点，尺寸远小于整幅图像。"""
        error = np.zeros((IR_HEIGHT, IR_WIDTH), dtype=np.float32)
        for n in (8, 4, 2):
            grid = _build_calibration_grid(error, n)
            expected = ((IR_HEIGHT + n - 1) // n + 1, (IR_WIDTH + n - 1) // n + 1)
            self.assertEqual(grid.shape, expected)
            self.assertLess(grid.size, error.size)

    def test_interpolate_calibration_grid_is_exact_for_linear_field(self) -> None:
        """双线性插值对线性场精确（使用各顶点名义位置处的值）。"""
        n, w, h = 4, 16, 16
        cols = w // n + 1
        rows = h // n + 1
        gy, gx = np.mgrid[0:rows, 0:cols]
        # 顶点名义位置 x=gx*n, y=gy*n 处的线性场值
        grid = (2.0 * (gx * n) + 3.0 * (gy * n) + 100.0).astype(np.float32)

        recon = _interpolate_calibration_grid(grid, (h, w), n)

        py, px = np.mgrid[0:h, 0:w]
        expected = (2.0 * px + 3.0 * py + 100.0).astype(np.float32)
        np.testing.assert_allclose(recon, expected, atol=1e-4)

    def test_calibration_grid_clamps_overflowing_vertices(self) -> None:
        """超出右/下边界的顶点应取最右/最下的采样值。"""
        w, h, n = 10, 10, 8
        error = np.arange(h * w, dtype=np.float32).reshape(h, w)
        grid = _build_calibration_grid(error, n)

        # 顶点 x/y 坐标: [0, 8, 16] -> clip 到 [0, 8, 9]。
        self.assertEqual(grid.shape, (3, 3))
        np.testing.assert_array_equal(grid[:, 0], error[[0, 8, 9], 0])
        np.testing.assert_array_equal(grid[:, 1], error[[0, 8, 9], 8])
        np.testing.assert_array_equal(grid[:, 2], error[[0, 8, 9], 9])
        np.testing.assert_array_equal(grid[0, :], error[0, [0, 8, 9]])
        np.testing.assert_array_equal(grid[2, :], error[9, [0, 8, 9]])

    def test_calibration_constant_offset_is_exactly_corrected(self) -> None:
        """均匀误差场校准后应精确减去该常数偏移。"""
        w, h, n = 16, 16, 4
        temp14 = np.full((h, w), 5000, dtype=np.uint16)
        error = np.full((h, w), 200.0, dtype=np.float32)
        grid = _build_calibration_grid(error, n)
        corrected = _apply_calibration(temp14, grid, n)
        np.testing.assert_array_equal(
            corrected, np.full((h, w), 4800, dtype=np.uint16)
        )

    def test_calibration_grid_bin_round_trip(self) -> None:
        """网格误差保存到 .bin 后能原样读回。"""
        w, h, n = 16, 16, 4
        error = np.arange(h * w, dtype=np.float32).reshape(h, w)
        grid = _build_calibration_grid(error, n)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grid_error_test.bin"
            save_calibration_grid_bin(grid, n, path)

            loaded_grid, loaded_n = load_calibration_grid_bin(path)
            self.assertEqual(loaded_n, n)
            self.assertEqual(loaded_grid.dtype, np.float32)
            np.testing.assert_array_equal(loaded_grid, grid)


if __name__ == "__main__":
    unittest.main()
