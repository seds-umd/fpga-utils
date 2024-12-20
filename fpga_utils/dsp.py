import numpy as np

from gps import gps_sim


# Calculate correlation between two signals, between 1 and -1
def corr(a: np.ndarray, b: np.ndarray):
    assert len(a) == len(b), f"Arrays must be the same length, {len(a)} != {len(b)}"

    a_norm = (a - np.mean(a)) / np.std(a)
    b_norm = (b - np.mean(b)) / np.std(b)

    return np.abs(np.sum(a_norm * b_norm.conjugate())) / len(a)


def complex_to_2bit(samples: np.ndarray):
    samples /= np.max([samples.real, samples.imag])
    samples *= 127 * 3 / 4

    samples_re = samples.real.astype(np.int8).astype(np.uint8) >> 6
    samples_im = samples.imag.astype(np.int8).astype(np.uint8) >> 6
    bits = samples_re | (samples_im << 2)
    bits = [int(x) for x in bits]

    return bits


def generate_gps_samples(
    fs: float,
    count: int,
    sv: int,
    doppler: float,
    sample_phase: int,
    noise_power: float,
    timestamp_offset: int = 0,
):
    """Generate GPS samples to send in IQ timestamp format.

    Args:
        fs (float): Sample rate in Hz
        count (int): Number of samples to generate
        sv (int): SV number (1 indexed)
        doppler (float): Doppler frequency shift
        sample_phase (int): Phase offset in number of samples
        noise_power (float): Noise power in dBm
        timestamp_offset (int): Value of timestamp of first sample

    Returns:
        (list[int], np.ndarray, np.ndarray): Packed bits, original samples, quantized samples
    """

    # 3/4 is about optimal for 33% magnitude bit density (per MAX2769 datasheet)
    samples = (3 / 4 * 127) * gps_sim.generate_gps(
        f_s=fs,
        n=int(count),
        sv=sv,
        doppler=doppler,
        sample_phase=sample_phase,
        signal_power=noise_power,
    )

    times_single = np.arange(4092)

    # Apply offset
    times_single = np.roll(times_single, -timestamp_offset)

    # Repeat
    times = np.tile(times_single, int(len(samples) / 4092) + 1)
    times = times.astype(np.uint16)[0 : len(samples)]

    # Convert to 4 bit format
    samples_re = samples.real.astype(np.int8).astype(np.uint8) >> 6
    samples_im = samples.imag.astype(np.int8).astype(np.uint8) >> 6
    bits = samples_re | (samples_im << 2) | (times << 4)
    bits = [int(x) for x in bits]

    # Get quantized samples
    samples_re = (samples_re << 6).astype(np.int8) | 0b100000
    samples_im = (samples_im << 6).astype(np.int8) | 0b100000

    samples_quant = samples_re + samples_im * 1j
    samples_quant /= 128

    return bits, samples, samples_quant

def from_sfix(val: int, peak: int, width: int):
    # 1 bit less because of sign
    shift = width - peak - 1

    if val >= 2 ** (width - 1):
        val = val - 2**width

    res = val / 2 ** (shift)

    return res

def to_sfix(val: float, peak: int, width: int):
    assert val <= 2**peak * (1.0 - (1.0 / 2 ** (width - 1)))
    assert val >= -(2**peak)

    shift = width - peak - 1

    if shift >= 0:
        val = val * (1 << shift)
    else:
        val = val / (1 << -shift)

    if val < 0:
        val = val + 2**width

    return int(val)
