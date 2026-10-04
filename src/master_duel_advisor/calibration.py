from pathlib import Path
from uuid import uuid4

import cv2

from .pipeline import save_json
from .regions import Calibration, Exemplar, Rect, Region, load_calibration


def calibrate_region(path: Path, image: Path, name: str, kind: str, rect: Rect, label: str | None = None, viewport: Rect | None = None):
    """Explicit user-labeled crop. Appends assets without overwriting exemplars."""
    calibration = load_calibration(path) if path.exists() else Calibration(name="user-calibration",regions={},viewport=viewport or Rect(x=0,y=0,width=1,height=1))
    if viewport is not None and viewport != calibration.viewport:
        raise ValueError("Viewport differs from existing calibration; create a separate layout")
    if kind in {"template","card","action"} and not label:
        raise ValueError("Template/card/action calibration requires a label")
    if kind in {"number","unobserved"} and label is not None:
        raise ValueError("Numeric/unobserved regions do not use template labels")
    pixels = cv2.imread(str(image))
    if pixels is None:
        raise ValueError("Cannot read calibration screenshot")
    view = calibration.viewport.crop(pixels)
    calibration.crop_regions(pixels)  # validate actual viewport aspect before writing
    previous = calibration.regions.get(name)
    if previous and (previous.rect != rect or previous.kind != kind):
        raise ValueError("Existing region geometry/kind differs; create a separate layout")
    exemplars = list(previous.exemplars) if previous else []
    asset = None
    if label is not None:
        relative = "templates/"+uuid4().hex+".png"
        asset = path.parent/relative
        asset.parent.mkdir(parents=True,exist_ok=True)
        if not cv2.imwrite(str(asset),rect.crop(view)):
            raise ValueError("Cannot save template crop")
        exemplars.append(Exemplar(label=label,image=relative))
    region = Region(rect=rect,kind=kind,exemplars=exemplars)
    calibration = calibration.model_copy(update={"regions":{**calibration.regions,name:region}})
    try:
        save_json(path,calibration.model_dump(mode="json"))
    except Exception:
        if asset is not None:
            asset.unlink(missing_ok=True)
        raise
    return calibration
