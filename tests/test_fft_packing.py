import unittest
import numpy as np
from fpga_utils.fft_sim import fft_pack_complex, fft_unpack_complex


class PackingTests(unittest.TestCase):
    def test_known_signed_iq_samples(self):
        samples = np.array([0, 0.5 - 0.5j, -1 + 127j / 128])
        self.assertEqual(fft_pack_complex(samples), [0x0000, 0xC040, 0x7F80])
        np.testing.assert_array_equal(fft_unpack_complex([0x0000, 0xC040, 0x7F80]), samples)


if __name__ == '__main__':
    unittest.main()
