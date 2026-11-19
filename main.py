"""Run this file in PyCharm to generate the timetable."""
import os
import sys
from pathlib import Path


def main(argv=None):
    """Start the command-line workflow with the supplied options."""
    from masar.cli import main as run
    return run(argv)


def _use_project_interpreter():
    """Use the local virtual environment even with stale IDE interpreter settings."""
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    interpreter = environment / "bin" / "python"
    if interpreter.is_file() and Path(sys.prefix).resolve() != environment.resolve():
        arguments = [str(interpreter)]
        if sys.dont_write_bytecode:
            arguments.append("-B")
        os.execv(str(interpreter), arguments + [str(root / "main.py"), *sys.argv[1:]])


if __name__ == "__main__":
    _use_project_interpreter()
    sys.exit(main())
