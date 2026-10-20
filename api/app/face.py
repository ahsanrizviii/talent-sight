"""Face templates for the identity check (Module 13, F7).

OpenCV's YuNet model finds the face and its landmarks; OpenCV's SFace model turns the face into 128
numbers (a template). Both models are Apache 2.0 and are downloaded into the image by the Dockerfile.
A picture arrives as a JPEG data URL, is read in memory and is thrown away: only the numbers are kept
(N16, N17). Nothing here writes a log line, so no picture or template can reach a log (N22).
"""

import base64
import binascii
import math
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.settings import settings

DETECTOR = "face_detection_yunet_2023mar.onnx"
RECOGNIZER = "face_recognition_sface_2021dec.onnx"
MAX_IMAGE_BYTES = 2_000_000
MATCH_AT = 0.363     # SFace's own cosine threshold for "same person" (OpenCV's documentation)
TURNED_AT = 0.25     # how far the nose must move off the middle of the eyes to count as a head turn
FACING_BELOW = 0.15  # less than this counts as looking straight at the camera
# In the camera's own picture (not the mirrored preview) a person turning to THEIR left moves the nose to
# the picture's right, so a positive turn means "to their left". Flip this to -1 if a test shows the opposite.
LEFT_SIGN = 1

LOCK = threading.Lock()  # the OpenCV models are not safe to use from two requests at once


class FaceError(Exception):
    """The picture cannot be used. The message is shown to the person."""


class FaceUnavailable(Exception):
    """Face matching is not set up on this server (the model files are missing)."""


@dataclass
class Face:
    template: list[float]  # 128 numbers
    turn: float            # 0 = facing the camera; positive = turned to their left, negative = to their right


def decode(image: str):
    import cv2
    import numpy as np

    data = image.split(",", 1)[1] if image.startswith("data:") else image
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise FaceError("The picture could not be read.") from error
    if len(raw) > MAX_IMAGE_BYTES:
        raise FaceError("The picture is too large.")
    picture = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if picture is None:
        raise FaceError("The picture could not be read.")
    return picture


@lru_cache
def models():
    import cv2

    folder = Path(settings.face_model_dir)
    if not (folder / DETECTOR).is_file() or not (folder / RECOGNIZER).is_file():
        raise FaceUnavailable("Face matching is not available: the model files are missing. Rebuild the API image.")
    detector = cv2.FaceDetectorYN.create(str(folder / DETECTOR), "", (320, 320), 0.8, 0.3, 5000)
    recognizer = cv2.FaceRecognizerSF.create(str(folder / RECOGNIZER), "")
    return detector, recognizer


def turn_of(face) -> float:
    """YuNet gives [x, y, w, h, right eye x, y, left eye x, y, nose x, y, ...]. How far the nose sits off
    the middle of the eyes, in eye widths: about 0 when facing the camera."""
    right_eye_x, left_eye_x, nose_x = float(face[4]), float(face[6]), float(face[8])
    middle = (right_eye_x + left_eye_x) / 2
    width = abs(left_eye_x - right_eye_x) or 1.0
    return LEFT_SIGN * (nose_x - middle) / width


def read_face(image: str) -> Face:
    """One face from one picture: its template and how far the head is turned."""
    picture = decode(image)
    with LOCK:
        detector, recognizer = models()
        height, width = picture.shape[:2]
        detector.setInputSize((width, height))
        _, faces = detector.detect(picture)
        if faces is None or len(faces) == 0:
            raise FaceError("No face was found. Look at the camera in good light.")
        if len(faces) > 1:
            raise FaceError("More than one face is in the picture. Only the candidate should be in view.")
        found = faces[0]
        feature = recognizer.feature(recognizer.alignCrop(picture, found))
    return Face(template=[round(float(x), 6) for x in feature.flatten()], turn=round(turn_of(found), 3))


def similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two templates, the same measure SFace's own match() uses."""
    dot = sum(x * y for x, y in zip(a, b))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / size if size else 0.0