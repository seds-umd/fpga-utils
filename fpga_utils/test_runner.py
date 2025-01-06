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
    scala_name: str = None,
    scala_object: str = None,
    verilog_name: str = None,
    package_path: str = None,
    spinal_sources: list = None,
    verilog_sources: list = None,
    sim: str = "icarus",
    scala: bool = True,
):
    """SpinalHDL wrapper for cocotb test runner

    Args:
        top_level (str): Name of top level SpinalHDL module
        package (str): Name of Scala package
        proj_dir (str): Relative path from testbench dir to project dir
        source_dir (str): Relative path from project dir to Spinal source dir
        gen_dir (str): Relative path from project dir to Spinal gen dir
        scala_name (str, optional): Name of Scala file. Defaults to $top_level.scala
        scala_object (str, optional): Name of Scala object that generates Verilog
        verilog_name (str, optional): Name of generated Verilog file. Defaults to $top_level.v
        package_path (str, optional): Submodule path to top level. Defaults to None
        spinal_sources (list, optional): List of extra SpinalHDL sources. Defaults to None
        verilog_sources (list, optional): List of extra Verilog sources. Defaults to None
        sim (str, optional): Simulator. Defaults to "icarus".
        scala (bool, optional): True for SpinalHDL source, False for Verilog source. Defaults to True
    """

    # TODO: multi level package path still isn't ideal

    sim = os.getenv("SIM", sim)

    if verilog_name == None:
        verilog_name = f"{top_level}.v"

    # Get path of top level script
    file_dir = Path(os.path.abspath(sys.argv[0])).parent

    proj_path = Path(file_dir / proj_dir).resolve()
    source_path = Path(proj_path / source_dir).resolve()
    gen_path = Path(proj_path / gen_dir / verilog_name).resolve()

    if scala_name == None:
        scala_name = top_level

    if scala_object == None:
        scala_object = f"{top_level}Verilog"

    if package_path is not None:
        sources = [source_path / package_path / f"{scala_name}.scala"]
    else:
        sources = [source_path / f"{scala_name}.scala"]

    if spinal_sources is not None:
        sources.extend([source_path / f"{source}.scala" for source in spinal_sources])

    if scala:
        if last_modified(sources) > last_modified(gen_path):
            if package_path is not None:
                cmd = ["sbt", f"runMain {package}.{package_path}.{scala_object}"]
            else:
                cmd = ["sbt", f"runMain {package}.{scala_object}"]
            print(" ".join(cmd))
            ret = subprocess.run(cmd, cwd=proj_path.resolve())
            assert ret.returncode == 0, "SpinalHDL error"
        else:
            print("Generated Verilog up to date, skipping regeneration")

    if verilog_sources is not None:
        verilog_sources = [proj_path / Path(p) for p in verilog_sources]
    else:
        verilog_sources = []

    if scala:
        verilog_sources.append(proj_path / gen_dir / verilog_name)

    runner = get_runner(sim)

    if sim == "verilator":
        build_args = ["-Wno-WIDTHTRUNC", "-Wno-WIDTHEXPAND"]
        run_args = ["--trace", "--trace-fst", "--trace-structs"]
        build_args.extend(run_args)
    else:
        build_args = []
        run_args = []

    runner.build(
        verilog_sources=verilog_sources,
        hdl_toplevel=top_level,
        always=True,
        waves=True,
        build_args=build_args,
    )

    runner.test(
        hdl_toplevel=top_level,
        test_module=f"test_{scala_name.lower()}",
        waves=True,
        test_args=run_args,
    )
