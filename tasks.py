import argparse
import os
import shutil
import subprocess
import tempfile
import zipfile
from typing import Callable

from bp_tools import __app_name__, __version__


def task(func: Callable) -> Callable:
    """
    Define function as a valid task using decorator.

    :param func: The function being
    :return: The function to call.
    """
    func.is_command = True  # type: ignore[attr-defined]
    return func


@task
def run_tests() -> None:
    """Run tests using pytest."""
    print("Running tests...")
    subprocess.check_call(["pytest"])


@task
def check_formatting() -> None:
    """Check code for formatting errors and fix where possible."""
    print("Sorting imports...")
    subprocess.check_call(["isort", "."])

    print("Formatting code with Black...")
    subprocess.check_call(["black", "."])

    print("Checking code style with Flake8...")
    subprocess.check_call(["flake8", "."])

    print("Performing type checks with MyPy...")
    subprocess.check_call(["mypy", "."])


@task
def build_executable() -> None:
    """Build executable from package."""
    print("Building executable...")
    pyinstaller_command = [
        "pyinstaller",
        "--onefile",
        "--name",
        __app_name__.replace(" ", "_"),
        "--icon",
        "assets/favicon.ico",
        "--add-data",
        ".venv/Lib/site-packages/pyfiglet/fonts;pyfiglet/fonts",
        os.path.join("aqua_sniper/__main__.py"),
    ]

    subprocess.check_call(pyinstaller_command)
    print("Executable built successfully.")

    os.remove(f"{__app_name__.replace(" ", "_")}.spec")
    shutil.rmtree("build")


@task
def build_dist() -> None:
    """Build distribution package for the application."""
    build_executable()

    with tempfile.TemporaryDirectory() as temp_dir:
        dir_name = f"{__app_name__.replace(" ", "_")}-v{__version__}"
        target_dir = os.path.join(temp_dir, dir_name)
        os.makedirs(target_dir, exist_ok=True)

        dist_directory = os.path.join("dist")
        os.makedirs(dist_directory, exist_ok=True)

        exe_path = os.path.join("dist", f"{__app_name__.replace(" ", "_")}.exe")
        files_to_include = [exe_path, "credentials.yaml", "README.md"]

        for file_path in files_to_include:
            if os.path.exists(file_path):
                shutil.copy(file_path, target_dir)
            else:
                print(f"Warning: {file_path} not found. Skipping.")

        zip_filename = os.path.join(dist_directory, f"{dir_name}.zip")
        with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as dist_zip:
            print("Creating distribution package...")
            for root, dirs, files in os.walk(target_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    dist_zip.write(
                        file_path, arcname=os.path.relpath(file_path, start=temp_dir)
                    )
        print("Distribution package created successfully.")


def main() -> None:
    """Parse commands from command line."""
    parser = argparse.ArgumentParser(description="Manage project tasks")
    parser.add_argument("task", type=str, help="Task to run")
    args = parser.parse_args()

    task_func = globals().get(args.task)
    if task_func and hasattr(task_func, "is_command"):
        task_func()
    else:
        print(f"Task '{args.task}' is invalid.")


if __name__ == "__main__":
    main()
