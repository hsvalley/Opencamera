from __future__ import annotations

from dataclasses import dataclass

import numpy as np

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - optional runtime dependency
    cv2 = None

from .models import InfraredFrame

IR_WIDTH = 260
IR_HEIGHT = 201
RAW_IR_HEIGHT = 202
IR_UVC_WIDTH = IR_WIDTH * 2
IR_UVC_BYTES_PER_PIXEL = 2
IR_BYTES_PER_LOGICAL_PIXEL = 4
DEFAULT_TEMP_MIN = 7616
DEFAULT_TEMP_MAX = 9502
DEFAULT_MEDIAN_KERNEL = 3


@dataclass(slots=True)
class InfraredProcessor:
    temp_min: int = DEFAULT_TEMP_MIN
    temp_max: int = DEFAULT_TEMP_MAX
    median_kernel: int = DEFAULT_MEDIAN_KERNEL

    def process(self, frame: np.ndarray) -> InfraredFrame:
        temp14 = decode_infrared_payload(frame)
        gray8 = clip_linear_stretch(temp14, min_val=self.temp_min, max_val=self.temp_max)
        filtered = median_filter(gray8, kernel_size=self.median_kernel)
        pseudo_rgb = gray_to_pseudo(filtered)
        return InfraredFrame(temp14=temp14, gray8=filtered, pseudo_rgb=pseudo_rgb)


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


def clip_linear_stretch(
    temp14: np.ndarray,
    min_val: int = DEFAULT_TEMP_MIN,
    max_val: int = DEFAULT_TEMP_MAX,
) -> np.ndarray:
    if temp14.size == 0:
        return np.zeros((IR_HEIGHT, IR_WIDTH), dtype=np.uint8)

    if max_val <= min_val:
        return np.zeros(temp14.shape, dtype=np.uint8)

    clipped = np.clip(temp14.astype(np.float32, copy=False), float(min_val), float(max_val))
    scaled = ((clipped - float(min_val)) * 255.0 / float(max_val - min_val)).astype(np.uint8)
    return histogram_equalize(scaled)


def histogram_equalize(gray8: np.ndarray) -> np.ndarray:
    if gray8.size == 0:
        return gray8.copy()
    if cv2 is not None:
        return cv2.equalizeHist(gray8)
    return _histogram_equalize_fallback(gray8)


def _histogram_equalize_fallback(gray8: np.ndarray) -> np.ndarray:
    hist = np.bincount(gray8.reshape(-1), minlength=256)
    cdf = hist.cumsum()
    nonzero = cdf[cdf > 0]
    if nonzero.size == 0:
        return gray8.copy()

    cdf_min = int(nonzero[0])
    total = int(gray8.size)
    if total == cdf_min:
        return np.zeros_like(gray8)

    lut = np.round((cdf - cdf_min) * 255.0 / (total - cdf_min)).clip(0, 255).astype(np.uint8)
    return lut[gray8]


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


def gray_to_pseudo(gray8: np.ndarray) -> np.ndarray:
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
