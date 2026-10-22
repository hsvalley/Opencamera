from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]          # 仓库根
PYTHON_DIR = Path(__file__).resolve().parents[1]    # OpenCamera_c/python
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from infrared_player.c_bridge import CBridge  # noqa: E402
from infrared_player.infrared import (  # noqa: E402
    IR_HEIGHT,
    IR_WIDTH,
    InfraredProcessor,
    decode_infrared_payload,
)

DATA = ROOT / "data" / "1.bin"

TEMP14_MAX = 0x3FFF
TEMP10_MAX = 0x03FF


def _load_raw() -> np.ndarray:
    return np.frombuffer(DATA.read_bytes(), dtype=np.uint8)


# --------------------------------------------------------------------------
# numpy 参考实现：逐模块按 c_model 源码复刻，用于端到端逐位比对
# --------------------------------------------------------------------------
def _gaussian_ref(img: np.ndarray) -> np.ndarray:
    kernel = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], dtype=np.int64)
    norm = 16
    padded = np.pad(img, 1, mode="edge").astype(np.int64)
    acc = np.zeros_like(img, dtype=np.int64)
    for dy in range(3):
        for dx in range(3):
            acc += padded[dy : dy + img.shape[0], dx : dx + img.shape[1]] * kernel[dy, dx]
    v = (acc + norm // 2) // norm
    return np.clip(v, 0, TEMP14_MAX).astype(np.uint16)


def _clip_single_frame_lowpass_ref(frame_min: int, frame_max: int) -> tuple[int, int]:
    """单帧动态极值截取（低通方式，默认）：首帧直接赋帧 min/max。"""
    return frame_min, frame_max


def _clip_single_frame_avg_ref(frame_min: int, frame_max: int) -> tuple[int, int]:
    """单帧动态极值截取（滑动窗口平均方式）：初始 cur=[0, TEMP14_MAX]，N=4，step=16。"""
    cur_min, cur_max = 0, TEMP14_MAX
    n, step = 4, 16
    sum_min, sum_max, cnt = frame_min, frame_max, 1
    avg_min, avg_max = sum_min // cnt, sum_max // cnt
    if abs(avg_min - cur_min) >= step:
        cur_min = avg_min
    if abs(avg_max - cur_max) >= step:
        cur_max = avg_max
    return cur_min, cur_max


def _median_ref(img: np.ndarray) -> np.ndarray:
    padded = np.pad(img, 1, mode="edge")
    windows = np.stack(
        [
            padded[dy : dy + img.shape[0], dx : dx + img.shape[1]]
            for dy in range(3)
            for dx in range(3)
        ],
        axis=0,
    )  # (9, H, W)
    return np.median(windows, axis=0).astype(np.uint16)


def _compress_ref(img: np.ndarray, min_val: int, max_val: int) -> np.ndarray:
    rng = max_val - min_val
    if rng == 0:
        return np.zeros_like(img, dtype=np.uint16)
    p = img.astype(np.int64)
    v = np.where(
        p <= min_val,
        0,
        np.where(p >= max_val, TEMP10_MAX, ((p - min_val) * TEMP10_MAX + rng // 2) // rng),
    )
    return v.astype(np.uint16)


def _hist_eq_ref(img: np.ndarray, reverse: bool = True) -> np.ndarray:
    count = img.size
    hist = np.bincount(img.ravel().astype(np.int64), minlength=TEMP10_MAX + 1)
    cdf = np.cumsum(hist)
    nonzero = np.nonzero(cdf)[0]
    if nonzero.size == 0:
        return np.zeros(img.shape, dtype=np.uint8)
    cdf_min = int(cdf[nonzero[0]])
    if count == 0 or count == cdf_min:
        return np.zeros(img.shape, dtype=np.uint8)
    gray = (cdf[img.astype(np.int64)] - cdf_min) * 255 // (count - cdf_min)
    if reverse:
        gray = 255 - gray
    return gray.astype(np.uint8)


def _pseudo_rgb_lut_ref() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    i = np.arange(256)
    r = np.zeros(256, dtype=np.uint8)
    g = np.zeros(256, dtype=np.uint8)
    b = np.zeros(256, dtype=np.uint8)
    m0 = i < 64
    m1 = (i >= 64) & (i < 128)
    m2 = (i >= 128) & (i < 192)
    m3 = i >= 192
    b[m0] = i[m0] * 4
    r[m1] = (i[m1] - 64) * 4
    b[m1] = 255 - (i[m1] - 64) * 4
    r[m2] = 255
    g[m2] = (i[m2] - 128) * 4
    r[m3] = 255
    g[m3] = 255
    b[m3] = (i[m3] - 192) * 4
    return r, g, b


def _color_ref(gray8: np.ndarray) -> np.ndarray:
    r, g, b = _pseudo_rgb_lut_ref()
    rgb = np.empty((*gray8.shape, 3), dtype=np.uint8)
    rgb[..., 0] = r[gray8]
    rgb[..., 1] = g[gray8]
    rgb[..., 2] = b[gray8]
    return rgb


class CBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = CBridge()  # 构造即 bridge_init，使用默认配置与内置 LUT

    def test_decode_matches_python_reference(self) -> None:
        raw = _load_raw()
        c_temp14 = self.bridge.decode(raw)
        py_temp14 = decode_infrared_payload(raw)

        self.assertEqual(c_temp14.shape, (IR_HEIGHT, IR_WIDTH))
        self.assertEqual(c_temp14.dtype, np.uint16)
        np.testing.assert_array_equal(c_temp14, py_temp14)

    def test_process_output_shapes(self) -> None:
        raw = _load_raw()
        temp14, gray8, rgb, mn, mx = self.bridge.process(raw, None)

        self.assertEqual(temp14.shape, (IR_HEIGHT, IR_WIDTH))
        self.assertEqual(gray8.shape, (IR_HEIGHT, IR_WIDTH))
        self.assertEqual(rgb.shape, (IR_HEIGHT, IR_WIDTH, 3))
        self.assertEqual(gray8.dtype, np.uint8)
        self.assertEqual(rgb.dtype, np.uint8)
        self.assertGreaterEqual(mn, 0)
        self.assertLessEqual(mx, TEMP14_MAX)
        self.assertLessEqual(mn, mx)

    def test_process_matches_numpy_reference(self) -> None:
        """端到端：C 流水线输出与 numpy 逐模块复刻逐位一致。"""
        raw = _load_raw()
        c_temp14, c_gray8, c_rgb, c_mn, c_mx = self.bridge.process(raw, None)

        temp14 = decode_infrared_payload(raw)
        np.testing.assert_array_equal(c_temp14, temp14)  # 校准前高斯前 = 采样输出

        gauss = _gaussian_ref(temp14)
        mn, mx = _clip_single_frame_lowpass_ref(int(gauss.min()), int(gauss.max()))
        compressed = _compress_ref(gauss, mn, mx)
        gray8 = _hist_eq_ref(compressed)
        rgb = _color_ref(gray8)

        self.assertEqual((c_mn, c_mx), (mn, mx))
        np.testing.assert_array_equal(c_gray8, gray8)
        np.testing.assert_array_equal(c_rgb, rgb)

    def test_process_reverse_false_matches_ascending_reference(self) -> None:
        """reverse=0 时应输出升序灰度（非反相）。"""
        bridge = CBridge()
        bridge.set_hist_reverse(False)
        raw = _load_raw()

        c_temp14, c_gray8, c_rgb, c_mn, c_mx = bridge.process(raw, None)

        temp14 = decode_infrared_payload(raw)
        gauss = _gaussian_ref(temp14)
        mn, mx = _clip_single_frame_lowpass_ref(int(gauss.min()), int(gauss.max()))
        compressed = _compress_ref(gauss, mn, mx)
        gray8 = _hist_eq_ref(compressed, reverse=False)
        rgb = _color_ref(gray8)

        self.assertEqual((c_mn, c_mx), (mn, mx))
        np.testing.assert_array_equal(c_gray8, gray8)
        np.testing.assert_array_equal(c_rgb, rgb)

    def test_process_median_filter_matches_reference(self) -> None:
        """filter_mode=中值时应与 numpy 中值参考逐位一致。"""
        bridge = CBridge()
        bridge.set_filter_mode(1)  # 中值
        raw = _load_raw()

        c_temp14, c_gray8, c_rgb, c_mn, c_mx = bridge.process(raw, None)

        temp14 = decode_infrared_payload(raw)
        med = _median_ref(temp14)
        mn, mx = _clip_single_frame_lowpass_ref(int(med.min()), int(med.max()))
        compressed = _compress_ref(med, mn, mx)
        gray8 = _hist_eq_ref(compressed)
        rgb = _color_ref(gray8)

        self.assertEqual((c_mn, c_mx), (mn, mx))
        np.testing.assert_array_equal(c_gray8, gray8)
        np.testing.assert_array_equal(c_rgb, rgb)

    def test_process_clip_avg_matches_reference(self) -> None:
        """calc_mode=平均时应与 numpy 滑动窗口平均参考逐位一致。"""
        bridge = CBridge()
        bridge.set_clip_calc_mode(0)  # 滑动窗口平均
        raw = _load_raw()

        c_temp14, c_gray8, c_rgb, c_mn, c_mx = bridge.process(raw, None)

        temp14 = decode_infrared_payload(raw)
        gauss = _gaussian_ref(temp14)
        mn, mx = _clip_single_frame_avg_ref(int(gauss.min()), int(gauss.max()))
        compressed = _compress_ref(gauss, mn, mx)
        gray8 = _hist_eq_ref(compressed)
        rgb = _color_ref(gray8)

        self.assertEqual((c_mn, c_mx), (mn, mx))
        np.testing.assert_array_equal(c_gray8, gray8)
        np.testing.assert_array_equal(c_rgb, rgb)


class InfraredProcessorTests(unittest.TestCase):
    def test_calibrate_then_calibrated_temp14_is_uniform(self) -> None:
        proc = InfraredProcessor()
        raw = _load_raw()
        proc.calibrate(raw)

        calibrated = proc.calibrated_temp14(raw)
        self.assertEqual(calibrated.shape, (IR_HEIGHT, IR_WIDTH))
        # 校准后各像素应退化为均值（均匀表面去 FPN）
        self.assertLessEqual(int(np.ptp(calibrated)), 1)

    def test_process_returns_infrared_frame(self) -> None:
        proc = InfraredProcessor()
        raw = _load_raw()
        frame = proc.process(raw)

        self.assertEqual(frame.gray8.shape, (IR_HEIGHT, IR_WIDTH))
        self.assertEqual(frame.pseudo_rgb.shape, (IR_HEIGHT, IR_WIDTH, 3))
        self.assertGreaterEqual(frame.clip_min, 0)
        self.assertLessEqual(frame.clip_max, TEMP14_MAX)


if __name__ == "__main__":
    unittest.main()
