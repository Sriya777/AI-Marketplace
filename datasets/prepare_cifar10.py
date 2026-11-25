"""
prepare_cifar10.py - turns the CIFAR-10 image dataset (named in the project presentation) into a small CSV the
marketplace can train on. The platform trains scikit-learn models on tabular data, so images are down-sampled
to 16x16 and flattened (256 grayscale features, or 768 with --color).

  python datasets/prepare_cifar10.py                          # downloads CIFAR-10 (~163 MB) from cs.toronto.edu
  python datasets/prepare_cifar10.py --source-dir <folder>    # use an already extracted 'cifar-10-batches-py'
  python datasets/prepare_cifar10.py --per-class 300 --color  # bigger / colour subset

Output: datasets/cifar10_subset.csv  (columns px_0 ... px_N, label)  -> use it from "Train Model" (sample list or upload).

NOTE: the batches are Python pickles from the official CIFAR-10 distribution; only point --source-dir at data you trust.
Expect modest accuracy (a few tens of percent) from classical models on raw pixels - CIFAR-10 is hard without CNNs.
"""
import argparse
import os
import pickle
import tarfile
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz"
DEFAULT_NAMES = ["airplane", "automobile", "bird", "cat", "deer", "dog", "frog", "horse", "ship", "truck"]


def download_and_extract(dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    tgz = os.path.join(dest_dir, "cifar-10-python.tar.gz")
    if not os.path.exists(tgz):
        print("downloading", URL)
        urllib.request.urlretrieve(URL, tgz)
    with tarfile.open(tgz) as t:
        t.extractall(dest_dir, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(dest_dir)
    return os.path.join(dest_dir, "cifar-10-batches-py")


def load_batches(src):
    xs, ys = [], []
    for i in range(1, 6):
        with open(os.path.join(src, f"data_batch_{i}"), "rb") as f:
            d = pickle.load(f, encoding="bytes")
        xs.append(np.asarray(d[b"data"], dtype=np.uint8)); ys.append(np.asarray(d[b"labels"]))
    names = DEFAULT_NAMES
    meta = os.path.join(src, "batches.meta")
    if os.path.exists(meta):
        with open(meta, "rb") as f:
            names = [n.decode() for n in pickle.load(f, encoding="bytes")[b"label_names"]]
    return np.concatenate(xs), np.concatenate(ys), names


def to_features(data, color):
    imgs = data.reshape(-1, 3, 32, 32).astype(np.float32)                  # N x C x H x W (R,G,B planes)
    pooled = imgs.reshape(-1, 3, 16, 2, 16, 2).mean(axis=(3, 5))           # 2x2 average pooling -> 16x16
    if not color:
        pooled = pooled.mean(axis=1, keepdims=True)                        # grayscale
    return pooled.reshape(len(data), -1).round(1)


def build_subset(data, labels, names, per_class, color, seed=42):
    rng = np.random.RandomState(seed)
    idx = np.concatenate([rng.choice(np.where(labels == c)[0], per_class, replace=False) for c in range(len(names))])
    rng.shuffle(idx)
    X = to_features(data[idx], color)
    df = pd.DataFrame(X, columns=[f"px_{i}" for i in range(X.shape[1])])
    df["label"] = [names[l] for l in labels[idx]]
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", help="extracted cifar-10-batches-py directory")
    ap.add_argument("--per-class", type=int, default=150)
    ap.add_argument("--color", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "cifar10_subset.csv"))
    a = ap.parse_args()
    src = a.source_dir or download_and_extract(os.path.join(HERE, ".cache"))
    data, labels, names = load_batches(src)
    df = build_subset(data, labels, names, a.per_class, a.color)
    df.to_csv(a.out, index=False)
    print(f"wrote {a.out}: {len(df)} rows x {df.shape[1]} columns, classes={df['label'].nunique()}")


if __name__ == "__main__":
    main()
