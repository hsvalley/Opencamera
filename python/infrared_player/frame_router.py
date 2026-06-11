from __future__ import annotations

import numpy as np

from .infrared import InfraredProcessor, bgr_to_rgb
from .models import CameraKind


class FrameRouter:
    def __init__(self, infrared_processor: InfraredProcessor | None = None) -> None:
        self.infrared_processor = infrared_processor or InfraredProcessor()

    def route(self, kind: CameraKind, frame: np.ndarray):
        if kind is CameraKind.NORMAL:
            return {"normal_rgb": bgr_to_rgb(frame)}
        return {"infrared": self.infrared_processor.process(frame)}
