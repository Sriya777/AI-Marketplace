# Datasets

The marketplace trains on **tabular classification CSVs** (features + one target column, last column by default).

| File | Source | Shape | Classes |
|---|---|---|---|
| `digits.csv` | scikit-learn bundled copy of the UCI "optical recognition of handwritten digits" set | 1797 × 64 | 10 |
| `iris.csv` | scikit-learn bundled (UCI Iris) | 150 × 4 | 3 |
| `wine.csv` | scikit-learn bundled (UCI Wine) | 178 × 13 | 3 |
| `breast_cancer.csv` | scikit-learn bundled (UCI Breast Cancer Wisconsin) | 569 × 30 | 2 |
| `cifar10_subset.csv` | **generated on demand** from CIFAR-10 (not shipped) | N × 256 | 10 |

Regenerate the bundled CSVs offline with `python datasets/make_sample_datasets.py`.

## CIFAR-10 (the dataset named in the project presentation)

```bash
python datasets/prepare_cifar10.py                       # downloads ~163 MB from cs.toronto.edu, writes cifar10_subset.csv
python datasets/prepare_cifar10.py --source-dir <dir>    # or reuse an already-downloaded cifar-10-batches-py folder
```

The script samples a class-balanced subset, 2×2 average-pools each image to 16×16 and flattens it
(256 grayscale features; `--color` gives 768). Classical models reach only modest accuracy on raw pixels –
that is expected; the point of the project is the cryptographic/blockchain pipeline, which is model-agnostic.

> The default demo uses `digits.csv` because it trains in seconds and reaches ~97 % accuracy.

## Using your own data

Upload any `.csv` from **Train Model → Upload**. Validation rejects: unparsable files, < 30 rows, < 2 columns,
a target with < 2 or > 50 distinct values (continuous/ID targets), classes with a single sample, duplicate column names,
and infinite values. Constant, all-missing and ID-like text columns are dropped with a warning; missing values are imputed.
