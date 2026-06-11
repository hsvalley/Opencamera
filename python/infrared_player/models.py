from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np


class CameraKind(str, Enum):
    NORMAL = "普通摄像头"
    INFRARED = "红外摄像头"


@dataclass(slots=True)
class CameraDevice:
    display_name: str
    camera_index: int
    backend_hint: Optional[str] = None


@dataclass(slots=True)
class InfraredFrame:
    temp14: np.ndarray
    gray8: np.ndarray
    pseudo_rgb: np.ndarray


@dataclass(slots=True)
class DisplayState:
    show_normal: bool = True
    show_gray: bool = True
    show_pseudo: bool = True
