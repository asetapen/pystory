import numpy as np

import pystory.recognition as recognition
from pystory.config import Config
from pystory.recognition import encode_face, encodings_path, is_recognized, load_encodings, save_encodings


def test_load_encodings_missing_file_returns_empty_list(tmp_path):
    config = Config(storage_dir=tmp_path)

    assert load_encodings(config) == []


def test_save_then_load_encodings_round_trip(tmp_path):
    config = Config(storage_dir=tmp_path)
    encodings = [np.arange(128, dtype=np.float64) * 0.01, np.ones(128, dtype=np.float64)]

    save_encodings(encodings, config)
    loaded = load_encodings(config)

    assert len(loaded) == len(encodings)
    for original, restored in zip(encodings, loaded):
        assert isinstance(restored, np.ndarray)
        np.testing.assert_array_equal(original, restored)


def test_save_encodings_creates_storage_dir(tmp_path):
    storage_dir = tmp_path / "nested" / "dir"
    config = Config(storage_dir=storage_dir)

    save_encodings([np.zeros(128)], config)

    assert encodings_path(config).exists()


# ---------------------------------------------------------------------------
# BGR->RGB must hand dlib a C-CONTIGUOUS array (issue: enroll crashed with a
# dlib TypeError -- "incompatible function arguments" -- that looked like a
# signature mismatch but was actually a memory-layout one).
#
# `frame[:, :, ::-1]` reverses the channel axis by making its stride negative
# rather than copying, so the result is a non-contiguous VIEW. dlib's
# pybind11 binding requires a C-contiguous uint8 buffer and rejects that view
# with the same confusing TypeError real face_recognition raises, so a fake
# that asserts contiguity (rather than needing a real dlib model + camera
# frame) reproduces the defect without the third-party boundary.
# ---------------------------------------------------------------------------

def _assert_contiguous_and_return(rgb, *args, **kwargs):
    assert rgb.flags["C_CONTIGUOUS"], "dlib rejects a non-contiguous array with a TypeError"
    return []


def test_encode_face_passes_a_contiguous_array_to_dlib(monkeypatch):
    monkeypatch.setattr(recognition.face_recognition, "face_encodings", _assert_contiguous_and_return)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)

    encode_face(frame)


def test_is_recognized_passes_a_contiguous_array_to_dlib(monkeypatch, tmp_path):
    config = Config(storage_dir=tmp_path)
    save_encodings([np.zeros(128)], config)
    monkeypatch.setattr(recognition.face_recognition, "face_encodings", _assert_contiguous_and_return)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)

    is_recognized(frame, config)
