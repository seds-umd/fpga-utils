import logging
import os
import subprocess
import sys
from cocotb.runner import get_runner
from pathlib import Path
from typing import List, Union


def last_modified(sources: Union[Path, List[Path]]):
    if type(sources) is list:
        t = 0

        for p in sources:
            mod = p.stat().st_mtime
            if mod > t:
                t = mod
    else:
        try:
            t = sources.stat().st_mtime
        except FileNotFoundError:
            t = 0

    return t


def run_wrapper(
    top_level: str,
    package: str,
    proj_dir: str,
    source_dir: str,
    gen_dir: str,
    package_path: str = None,
    spinal_sources: list = None,
    verilog_sources: list = None,
    sim: str = "icarus",
):
    """SpinalHDL wrapper for cocotb test runner

    Args:
        top_level (str): Name of top level SpinalHDL module
        proj_dir (str): Relative path from testbench dir to project dir
        source_dir (str): Relative path from project dir to Spinal source dir
        gen_dir (str): Relative path from project dir to Spinal gen dir
        package_path (str): Submodule path to top level
        spinal_sources (list, optional): List of extra SpinalHDL sources. Defaults to None.
        verilog_sources (list, optional): List of extra Verilog sources. Defaults to None.
        sim (str, optional): Simulator. Defaults to "icarus".
    """

    sim = os.getenv("SIM", sim)

    # Get path of top level script
    file_dir = Path(os.path.abspath(sys.argv[0])).parent

    proj_path = Path(file_dir / proj_dir).resolve()
    source_path = Path(proj_path / source_dir).resolve()
    gen_path = Path(proj_path / gen_dir / f"{top_level}.v").resolve()

    sources = [source_path / package_path / f"{top_level}.scala"]

    if spinal_sources is not None:
        sources.extend([source_path / f"{source}.scala" for source in spinal_sources])

    if last_modified(sources) > last_modified(gen_path):
        ret = subprocess.run(
            ["sbt", f"runMain {package}.{package_path}.{top_level}Verilog"], cwd=proj_path.resolve()
        )
        assert ret.returncode == 0, "SpinalHDL error"
    else:
        print("Generated Verilog up to date, skipping regeneration")

    if verilog_sources is not None:
        verilog_sources = [proj_path / Path(p) for p in verilog_sources]
    else:
        verilog_sources = []
    verilog_sources.append(proj_path / gen_dir / f"{top_level}.v")

    runner = get_runner(sim)

    runner.build(
        verilog_sources=verilog_sources,
        hdl_toplevel=top_level,
        always=True,
        waves=True,
    )

    runner.test(
        hdl_toplevel=top_level,
        test_module=f"test_{top_level.lower()}",
        waves=True,
    )
