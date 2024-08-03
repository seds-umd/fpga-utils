from setuptools import setup

setup(
    name="fpga-utils",
    version="0.1",
    packages=["fpga_utils"],
    install_requires=["cocotb>=1.9.0,<2"],
    scripts=["scripts/waves"]
)
