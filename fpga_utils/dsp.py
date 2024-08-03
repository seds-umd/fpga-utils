import numpy as np

# Calculate correlation between two signals, between 1 and -1
def corr(a: np.ndarray, b: np.ndarray):
    assert len(a) == len(b), f"Arrays must be the same length, {len(a)} != {len(b)}"

    a_norm = (a - np.mean(a)) / np.std(a)
    b_norm = (b - np.mean(b)) / np.std(b)

    return np.abs(np.sum(a_norm * b_norm.conjugate())) / len(a)
