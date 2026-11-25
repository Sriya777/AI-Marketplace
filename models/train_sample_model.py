"""
train_sample_model.py  (v2)
Trains a neural network iteratively, epoch by epoch, printing loss/accuracy
each round and saving a training curve plot. The point: the marketplace's
whole premise is protecting a model that took real training effort - so
the demo should visibly SHOW training happening (multiple epochs,
improving accuracy, a loss curve), not just call .fit() once and move on.

Run: python models/train_sample_model.py
Produces:
    models/artifacts/mnist_classifier.joblib   <- the "product" to protect
    models/artifacts/training_curve.png         <- proof-of-work evidence
"""

import os
import warnings
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.datasets import load_digits
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import accuracy_score, log_loss
from sklearn.exceptions import ConvergenceWarning

warnings.filterwarnings("ignore", category=ConvergenceWarning)  # expected: we
# intentionally call .fit() once per epoch via warm_start, so sklearn's
# internal "hasn't converged in 1 iteration" warning is noise here, not a bug

OUT_DIR = os.path.join(os.path.dirname(__file__), "artifacts")
MODEL_PATH = os.path.join(OUT_DIR, "mnist_classifier.joblib")
CURVE_PATH = os.path.join(OUT_DIR, "training_curve.png")

EPOCHS = 60
HIDDEN_LAYERS = (256, 128, 64)  # deliberately over-provisioned vs. the simple
                                  # digits dataset, so the saved weight file
                                  # is a meaningfully large artifact to protect


def train_and_save():
    os.makedirs(OUT_DIR, exist_ok=True)

    digits = load_digits()
    X_train, X_test, y_train, y_test = train_test_split(
        digits.data, digits.target, test_size=0.2, random_state=42
    )
    classes = np.unique(y_train)

    model = MLPClassifier(
        hidden_layer_sizes=HIDDEN_LAYERS,
        learning_rate_init=0.001,
        warm_start=True,   # lets us call .fit repeatedly and keep learned weights
        max_iter=1,        # one internal epoch per .fit() call
        random_state=42,
    )

    train_acc_history, test_acc_history, loss_history = [], [], []

    print(f"Training MLP {HIDDEN_LAYERS} for {EPOCHS} epochs on {len(X_train)} samples...")
    for epoch in range(1, EPOCHS + 1):
        model.fit(X_train, y_train)  # one more epoch, weights carried over (warm_start)

        train_acc = accuracy_score(y_train, model.predict(X_train))
        test_acc = accuracy_score(y_test, model.predict(X_test))
        loss = log_loss(y_train, model.predict_proba(X_train), labels=classes)

        train_acc_history.append(train_acc)
        test_acc_history.append(test_acc)
        loss_history.append(loss)

        if epoch % 5 == 0 or epoch == 1:
            print(f"  Epoch {epoch:3d}/{EPOCHS}  "
                  f"loss={loss:.4f}  train_acc={train_acc:.4f}  test_acc={test_acc:.4f}")

    print(f"\nFinal test accuracy: {test_acc_history[-1]:.4f}")

    # Save the trained model - this is the artifact the rest of the
    # pipeline (upload.py) will encrypt, hash, Merkle-root, sign, and
    # register on-chain.
    joblib.dump(model, MODEL_PATH)
    print(f"Saved model artifact to: {MODEL_PATH}")
    print(f"File size: {os.path.getsize(MODEL_PATH)} bytes")

    # Save a training curve as visible proof-of-work for the demo/report -
    # this is what justifies "this model is worth protecting."
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
    ax1.plot(range(1, EPOCHS + 1), loss_history)
    ax1.set_title("Training Loss")
    ax1.set_xlabel("Epoch")
    ax1.set_ylabel("Log Loss")

    ax2.plot(range(1, EPOCHS + 1), train_acc_history, label="Train")
    ax2.plot(range(1, EPOCHS + 1), test_acc_history, label="Test")
    ax2.set_title("Accuracy")
    ax2.set_xlabel("Epoch")
    ax2.set_ylabel("Accuracy")
    ax2.legend()

    fig.tight_layout()
    fig.savefig(CURVE_PATH, dpi=120)
    print(f"Saved training curve to: {CURVE_PATH}")

    return MODEL_PATH


if __name__ == "__main__":
    train_and_save()
