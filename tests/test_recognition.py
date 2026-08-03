import numpy as np

from pystory.config import Config
from pystory.recognition import encodings_path, load_encodings, save_encodings


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
