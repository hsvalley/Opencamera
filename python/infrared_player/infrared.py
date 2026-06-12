from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - optional runtime dependency
    cv2 = None

from .models import InfraredFrame

# LUT cache for gray2rgb.txt
_lut_cache: np.ndarray | None = None
_lut_checked: bool = False

IR_WIDTH = 260
IR_HEIGHT = 201
RAW_IR_HEIGHT = 202
IR_UVC_WIDTH = IR_WIDTH * 2
IR_UVC_BYTES_PER_PIXEL = 2
IR_BYTES_PER_LOGICAL_PIXEL = 4
DEFAULT_MEDIAN_KERNEL = 3


@dataclass(slots=True)
class InfraredProcessor:
    median_kernel: int = DEFAULT_MEDIAN_KERNEL
    calibration_map: np.ndarray | None = field(default=None)

    def calibrate(self, frame: np.ndarray) -> None:
        """从当前原始帧计算校准误差图（各像素与均值的差）。"""
        temp14 = decode_infrared_payload(frame)
        mean_val = float(temp14.mean())
        self.calibration_map = temp14.astype(np.float32) - mean_val

    def process(self, frame: np.ndarray) -> InfraredFrame:
        temp14 = decode_infrared_payload(frame)
        if self.calibration_map is not None:
            temp14 = _apply_calibration(temp14, self.calibration_map)
        gray8 = clip_linear_stretch(temp14)
        filtered = median_filter(gray8, kernel_size=self.median_kernel)
        inverted = 255 - filtered
        pseudo_rgb = gray_to_pseudo(inverted)
        return InfraredFrame(temp14=temp14, gray8=inverted, pseudo_rgb=pseudo_rgb)


def decode_infrared_payload(frame: np.ndarray) -> np.ndarray:
    payload = np.ascontiguousarray(frame).view(np.uint8).reshape(-1)
    expected_size = IR_WIDTH * RAW_IR_HEIGHT * IR_BYTES_PER_LOGICAL_PIXEL
    if payload.size != expected_size:
        raise ValueError(
            f"Unexpected infrared payload size: {payload.size}, expected {expected_size}"
        )

    pixels = payload.reshape(RAW_IR_HEIGHT, IR_WIDTH, IR_BYTES_PER_LOGICAL_PIXEL)
    nibbles = pixels >> 4
    value16 = (
        (nibbles[:, :, 0].astype(np.uint16) << 12)
        | (nibbles[:, :, 1].astype(np.uint16) << 8)
        | (nibbles[:, :, 2].astype(np.uint16) << 4)
        | nibbles[:, :, 3].astype(np.uint16)
    )
    return (value16 & 0x3FFF)[:IR_HEIGHT, :]


def _apply_calibration(temp14: np.ndarray, calibration_map: np.ndarray) -> np.ndarray:
    """用校准误差图校正原始温度数据。"""
    corrected = temp14.astype(np.float32) - calibration_map
    return np.clip(corrected, 0, 0x3FFF).astype(np.uint16)


def clip_linear_stretch(temp14: np.ndarray) -> np.ndarray:
    if temp14.size == 0:
        return np.zeros((IR_HEIGHT, IR_WIDTH), dtype=np.uint8)

    return histogram_equalize_temperature(temp14)


def histogram_equalize_temperature(temp14: np.ndarray) -> np.ndarray:
    """直接对原始温度值做直方图均衡，输出 0-255 灰度图。"""
    if temp14.size == 0:
        return np.zeros((IR_HEIGHT, IR_WIDTH), dtype=np.uint8)

    return _histogram_equalize_raw(temp14)


def _histogram_equalize_raw(temp14: np.ndarray) -> np.ndarray:
    """直接在原始温度值上做直方图均衡，输出 0-255 灰度图。"""
    data_min = int(temp14.min())
    data_max = int(temp14.max())
    if data_min == data_max:
        return np.zeros(temp14.shape, dtype=np.uint8)

    temp_range = data_max - data_min + 1
    indices = (temp14.astype(np.int32) - data_min).reshape(-1)
    hist = np.bincount(indices, minlength=temp_range)
    cdf = hist.cumsum()
    nonzero = cdf[cdf > 0]
    if nonzero.size == 0:
        return np.zeros(temp14.shape, dtype=np.uint8)

    cdf_min = int(nonzero[0])
    total = int(temp14.size)
    if total == cdf_min:
        return np.zeros(temp14.shape, dtype=np.uint8)

    lut = np.round(
        (cdf - cdf_min) * 255.0 / (total - cdf_min)
    ).clip(0, 255).astype(np.uint8)
    return lut[indices].reshape(temp14.shape)


def median_filter(gray8: np.ndarray, kernel_size: int = DEFAULT_MEDIAN_KERNEL) -> np.ndarray:
    if kernel_size <= 1:
        return gray8.copy()
    if kernel_size % 2 == 0:
        kernel_size += 1
    if cv2 is not None:
        return cv2.medianBlur(gray8, kernel_size)
    return _median_filter_fallback(gray8, kernel_size)


def _median_filter_fallback(gray8: np.ndarray, kernel_size: int) -> np.ndarray:
    pad = kernel_size // 2
    padded = np.pad(gray8, pad, mode="edge")
    result = np.empty_like(gray8)
    for y in range(gray8.shape[0]):
        for x in range(gray8.shape[1]):
            window = padded[y : y + kernel_size, x : x + kernel_size]
            result[y, x] = np.median(window)
    return result


def _load_gray2rgb_lut() -> np.ndarray | None:
    """加载当前工作目录下的 gray2rgb.txt 作为伪彩色查找表，仅加载一次。"""
    global _lut_cache, _lut_checked
    if _lut_checked:
        return _lut_cache
    _lut_checked = True

    lut_path = Path.cwd() / "gray2rgb.txt"
    if not lut_path.is_file():
        return None

    try:
        data = np.loadtxt(lut_path, delimiter=",", skiprows=1, dtype=np.uint8)
    except Exception:
        return None

    if data.ndim != 2 or data.shape != (256, 4):
        return None
    if not np.array_equal(data[:, 0], np.arange(256, dtype=np.uint8)):
        return None

    _lut_cache = data[:, 1:4]  # RGB columns
    return _lut_cache


def gray_to_pseudo(gray8: np.ndarray) -> np.ndarray:
    lut = _load_gray2rgb_lut()
    if lut is not None:
        return lut[gray8].copy()

    gray = gray8.astype(np.uint8, copy=False)
    rgb = np.zeros((*gray.shape, 3), dtype=np.uint8)

    mask0 = gray < 64
    mask1 = (gray >= 64) & (gray < 128)
    mask2 = (gray >= 128) & (gray < 192)
    mask3 = gray >= 192

    rgb[mask0, 2] = gray[mask0] * 4

    rgb[mask1, 0] = (gray[mask1] - 64) * 4
    rgb[mask1, 2] = 255 - (gray[mask1] - 64) * 4

    rgb[mask2, 0] = 255
    rgb[mask2, 1] = (gray[mask2] - 128) * 4

    rgb[mask3, 0] = 255
    rgb[mask3, 1] = 255
    rgb[mask3, 2] = (gray[mask3] - 192) * 4
    return rgb


def bgr_to_rgb(frame: np.ndarray) -> np.ndarray:
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"Expected BGR frame, got shape {frame.shape}")
    return frame[:, :, ::-1].copy()
