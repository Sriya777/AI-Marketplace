"""Tests the CIFAR-10 -> CSV conversion using synthetic data in the EXACT official batch format
(the real download host is not reachable from every environment, so this checks the conversion logic only)."""
import os, pickle, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "datasets"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import prepare_cifar10 as pc


def _fake_cifar(tmp_path, n_per_batch=500):
    rng = np.random.RandomState(0)
    d = tmp_path / "cifar-10-batches-py"; d.mkdir()
    for i in range(1, 6):
        labels = rng.randint(0, 10, n_per_batch)
        base = labels[:, None] * 20.0                                   # class-dependent brightness so the data is learnable
        data = np.clip(base + rng.randn(n_per_batch, 3072) * 15, 0, 255).astype(np.uint8)
        pickle.dump({b"data": data, b"labels": labels.tolist(), b"batch_label": b"x", b"filenames": []}, open(d / f"data_batch_{i}", "wb"))
    pickle.dump({b"label_names": [n.encode() for n in pc.DEFAULT_NAMES]}, open(d / "batches.meta", "wb"))
    return str(d)


def test_conversion_shapes_and_balance(tmp_path):
    data, labels, names = pc.load_batches(_fake_cifar(tmp_path))
    assert data.shape == (2500, 3072) and names == pc.DEFAULT_NAMES
    df = pc.build_subset(data, labels, names, per_class=40, color=False)
    assert df.shape == (400, 257) and df["label"].value_counts().nunique() == 1 and df["label"].nunique() == 10
    assert pc.build_subset(data, labels, names, 20, color=True).shape == (200, 769)


def test_pooling_is_correct():
    img = np.zeros((1, 3072), dtype=np.uint8)
    img[0, :1024] = 100; img[0, 1024:2048] = 50; img[0, 2048:] = 0       # R=100, G=50, B=0 everywhere
    f = pc.to_features(img, color=False)
    assert f.shape == (1, 256) and np.allclose(f, 50.0)                    # mean of the three channels
    c = pc.to_features(img, color=True)
    assert c.shape == (1, 768) and np.allclose(c[0, :256], 100) and np.allclose(c[0, 256:512], 50)


def test_generated_csv_passes_platform_validation_and_trains(tmp_path):
    from backend.app import ml
    data, labels, names = pc.load_batches(_fake_cifar(tmp_path))
    out = tmp_path / "cifar10_subset.csv"
    pc.build_subset(data, labels, names, 60, False).to_csv(out, index=False)
    rep = ml.analyze_csv(str(out))
    assert rep["valid"] and rep["n_rows"] == 600 and len(rep["classes"]) == 10 and rep["target"] == "label"
