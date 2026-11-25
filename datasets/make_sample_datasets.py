"""
Generates small CSV classification datasets from scikit-learn's BUNDLED copies of public datasets
(no network access needed). Last column = target.

  digits.csv         1797 x 64 pixel features, 10 classes   (UCI optical recognition of handwritten digits)
  iris.csv            150 x 4,  3 classes
  wine.csv            178 x 13, 3 classes
  breast_cancer.csv   569 x 30, 2 classes

For CIFAR-10 (the dataset named in the project presentation) see prepare_cifar10.py.
Run: python datasets/make_sample_datasets.py
"""
import os
import pandas as pd
from sklearn import datasets

HERE = os.path.dirname(os.path.abspath(__file__))

def save(name, bunch, target_name="target"):
    df = pd.DataFrame(bunch.data, columns=[str(c).replace(" ", "_") for c in bunch.feature_names])
    df[target_name] = [bunch.target_names[t] if name != "digits" else int(t) for t in bunch.target]
    path = os.path.join(HERE, f"{name}.csv")
    df.to_csv(path, index=False)
    print(f"{name}.csv  rows={len(df)} cols={df.shape[1]}  classes={df[target_name].nunique()}")

save("iris", datasets.load_iris(), "species")
save("wine", datasets.load_wine(), "cultivar")
save("breast_cancer", datasets.load_breast_cancer(), "diagnosis")
save("digits", datasets.load_digits(), "digit")
