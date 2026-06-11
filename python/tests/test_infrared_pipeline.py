from __future__ import annotations

import sys
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
    DEFAULT_TEMP_MAX,
    DEFAULT_TEMP_MIN,
    InfraredProcessor,
    clip_linear_stretch,
    decode_infrared_payload,
    gray_to_pseudo,
    median_filter,
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

    def test_clip_stretch_uses_fixed_temperature_range(self) -> None:
        temp14 = np.array(
            [
                [DEFAULT_TEMP_MIN - 10, DEFAULT_TEMP_MIN, (DEFAULT_TEMP_MIN + DEFAULT_TEMP_MAX) // 2],
                [DEFAULT_TEMP_MAX, DEFAULT_TEMP_MAX + 10, DEFAULT_TEMP_MIN + 1],
            ],
            dtype=np.uint16,
        )

        gray8 = clip_linear_stretch(temp14)

        self.assertEqual(int(gray8[0, 0]), 0)
        self.assertLessEqual(int(gray8[0, 1]), 5)
        self.assertGreaterEqual(int(gray8[1, 0]), 250)
        self.assertEqual(int(gray8[1, 1]), 255)
        self.assertTrue(0 < int(gray8[0, 2]) < 255)

    def test_decode_drops_last_raw_row(self) -> None:
        raw_rows = np.zeros((RAW_IR_HEIGHT, IR_WIDTH, 4), dtype=np.uint8)
        raw_rows[-1, :, :] = 0xF0
        frame = raw_rows.reshape(RAW_IR_HEIGHT, IR_UVC_WIDTH, 2)

        decoded = decode_infrared_payload(frame)

        self.assertEqual(decoded.shape, (IR_HEIGHT, IR_WIDTH))
        self.assertTrue(np.all(decoded[-1] == 0))


if __name__ == "__main__":
    unittest.main()
