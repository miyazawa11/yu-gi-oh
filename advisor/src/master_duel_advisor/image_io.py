"""日本語を含む Windows のパスでも画像を読み書きします。"""
from pathlib import Path

import cv2
import numpy as np


def read_image(path):
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if not data:
        return None
    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


def write_image(path, pixels):
    path = Path(path)
    success, encoded = cv2.imencode(path.suffix, pixels)
    if not success:
        return False
    path.write_bytes(encoded.tobytes())
    return True
