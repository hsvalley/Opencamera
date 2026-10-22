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
IR_HEIGHT = 202
RAW_IR_HEIGHT = 202
IR_UVC_WIDTH = IR_WIDTH * 2
IR_UVC_BYTES_PER_PIXEL = 2
IR_BYTES_PER_LOGICAL_PIXEL = 4
DEFAULT_MEDIAN_KERNEL = 3
DEFAULT_BILATERAL_D = 5
DEFAULT_BILATERAL_SIGMA_COLOR = 75.0
DEFAULT_BILATERAL_SIGMA_SPACE = 5.0
DEFAULT_CALIBRATION_N = 8
CALIBRATION_N_CHOICES = (8, 4, 2)


@dataclass(slots=True)
class InfraredProcessor:
    bilateral_d: int = DEFAULT_BILATERAL_D
    bilateral_sigma_color: float = DEFAULT_BILATERAL_SIGMA_COLOR
    bilateral_sigma_space: float = DEFAULT_BILATERAL_SIGMA_SPACE
    median_kernel: int = DEFAULT_MEDIAN_KERNEL
    calibration_n: int = DEFAULT_CALIBRATION_N
    calibration_map: np.ndarray | None = field(default=None)

    def calibrate(self, frame: np.ndarray) -> None:
        """从当前原始帧计算校准误差，并下采样为 n×n 网格（各顶点与均值的差）。"""
        temp14 = decode_infrared_payload(frame)
        mean_val = float(temp14.mean())
        error = temp14.astype(np.float32) - mean_val
        self.calibration_map = _build_calibration_grid(error, self.calibration_n)

    def calibrated_temp14(self, frame: np.ndarray) -> np.ndarray:
        """返回校准后（未滤波）的 14-bit 原始温度数据。"""
        temp14 = decode_infrared_payload(frame)
        if self.calibration_map is not None:
            temp14 = _apply_calibration(temp14, self.calibration_map, self.calibration_n)
        return temp14

    def process(self, frame: np.ndarray) -> InfraredFrame:
        temp14 = decode_infrared_payload(frame)
        if self.calibration_map is not None:
            temp14 = _apply_calibration(temp14, self.calibration_map, self.calibration_n)
        temp14 = bilateral_filter_14bit(
            temp14,
            d=self.bilateral_d,
            sigma_color=self.bilateral_sigma_color,
            sigma_space=self.bilateral_sigma_space,
        )
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


def _apply_calibration(
    temp14: np.ndarray, calibration_grid: np.ndarray, n: int
) -> np.ndarray:
    """用校准误差网格校正原始温度数据。"""
    error = _interpolate_calibration_grid(calibration_grid, temp14.shape, n)
    corrected = temp14.astype(np.float32) - error
    return np.clip(corrected, 0, 0x3FFF).astype(np.uint16)


def _build_calibration_grid(error: np.ndarray, n: int) -> np.ndarray:
    """将逐像素校准误差图下采样为 n×n 网格，仅保存每个正方形的 4 个顶点。

    相邻正方形共享顶点，因此网格尺寸为 (ceil(H/n)+1, ceil(W/n)+1)。
    超出图像右/下边界的顶点取最右/最下的采样值。
    """
    h, w = error.shape
    cols = (w + n - 1) // n  # ceil(w / n)
    rows = (h + n - 1) // n  # ceil(h / n)
    xs = np.clip(np.arange(cols + 1) * n, 0, w - 1)
    ys = np.clip(np.arange(rows + 1) * n, 0, h - 1)
    return error[np.ix_(ys, xs)]


def _interpolate_calibration_grid(
    grid: np.ndarray, shape: tuple[int, int], n: int
) -> np.ndarray:
    """对每个像素按其所在 n×n 正方形做双线性插值，重建逐像素误差图。"""
    h, w = shape
    rows, cols = grid.shape
    xx = np.arange(w)
    yy = np.arange(h)
    ci = xx // n
    cj = yy // n
    u = (xx - ci * n).astype(np.float32) / n
    v = (yy - cj * n).astype(np.float32) / n

    top_left = grid[cj[:, None], ci[None, :]]
    top_right = grid[cj[:, None], ci[None, :] + 1]
    bottom_left = grid[cj[:, None] + 1, ci[None, :]]
    bottom_right = grid[cj[:, None] + 1, ci[None, :] + 1]

    top = top_left * (1.0 - u[None, :]) + top_right * u[None, :]
    bottom = bottom_left * (1.0 - u[None, :]) + bottom_right * u[None, :]
    return top * (1.0 - v[:, None]) + bottom * v[:, None]


def save_temp14_bin(temp14: np.ndarray, path: Path) -> None:
    """将 14-bit 温度数据导出为大端序 .bin（每像素 2 字节，高位在前）。"""
    if temp14.dtype != np.uint16:
        temp14 = temp14.astype(np.uint16)
    path.write_bytes(temp14.astype(">u2").tobytes())


def save_calibration_grid_bin(grid: np.ndarray, n: int, path: Path) -> None:
    """将校准误差网格保存为 .bin：头部为 [n, rows, cols] 三个 int32，后跟 float32 数据。"""
    if grid.dtype != np.float32:
        grid = grid.astype(np.float32)
    header = np.array([n, grid.shape[0], grid.shape[1]], dtype=np.int32)
    path.write_bytes(header.tobytes() + grid.tobytes())


def load_calibration_grid_bin(path: Path) -> tuple[np.ndarray, int]:
    """从 .bin 加载校准误差网格，返回 (grid, n)。"""
    raw = path.read_bytes()
    if len(raw) < 12:
        raise ValueError(f"校准网格文件过短: {path}")
    header = np.frombuffer(raw[:12], dtype=np.int32)
    n, rows, cols = int(header[0]), int(header[1]), int(header[2])
    grid = np.frombuffer(raw[12:], dtype=np.float32).reshape(rows, cols)
    return grid, n


def compute_ooc(temp14: np.ndarray) -> np.ndarray:
    """为每个像素计算 4-bit ooc 值（0-15）。

    ooc = 7 + (12000 - 原始像素值) / 700，四舍五入后裁剪到 [0, 15]。
    """
    ooc = 7.0 + (12000.0 - temp14.astype(np.float32)) / 700.0
    return np.rint(ooc).clip(0, 15).astype(np.uint8)


def pack_ooc_bytes(ooc: np.ndarray) -> np.ndarray:
    """每 2 个像素组成一个字节：偶数像素高 4 位，奇数像素低 4 位。"""
    flat = ooc.astype(np.uint8).reshape(-1)
    even = flat[0::2]  # 索引 0, 2, 4, ...
    odd = flat[1::2]  # 索引 1, 3, 5, ...
    return (even << 4) | odd


def save_ooc_txt(temp14: np.ndarray, path: Path) -> None:
    """按 ooc 规则将 14-bit 温度数据打包为字节，以 "0xDD, " 格式写入文本文件。"""
    packed = pack_ooc_bytes(compute_ooc(temp14))
    text = ", ".join(f"0x{b:02X}" for b in packed)
    path.write_text(text, encoding="ascii")


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


def bilateral_filter_14bit(
    temp14: np.ndarray,
    d: int = DEFAULT_BILATERAL_D,
    sigma_color: float = DEFAULT_BILATERAL_SIGMA_COLOR,
    sigma_space: float = DEFAULT_BILATERAL_SIGMA_SPACE,
) -> np.ndarray:
    """在 14-bit 温度数据上做双边滤波，保边去噪。

    双边滤波在平滑区域去噪的同时保留温度边缘（物体轮廓），
    在直方图均衡之前执行，避免 HE 放大传感器噪声。
    """
    if d <= 0:
        return temp14.copy()

    if cv2 is not None:
        img_f32 = temp14.astype(np.float32)
        filtered = cv2.bilateralFilter(img_f32, d, sigma_color, sigma_space)
        return np.clip(np.round(filtered), 0, 0x3FFF).astype(np.uint16)

    # 无 OpenCV 时的 fallback：中值滤波
    k = d if d % 2 == 1 else d + 1
    padded = np.pad(temp14, k // 2, mode="edge")
    result = np.empty_like(temp14)
    for y in range(temp14.shape[0]):
        for x in range(temp14.shape[1]):
            window = padded[y : y + k, x : x + k]
            result[y, x] = np.median(window)
    return result


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
