"""Run the generator from a checkout of its repository (a submodule of a
project): `python generate.py ...` is the command `lhtml-site ...` of an
installation (pip install), whose code is in src/lhtml_site/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from lhtml_site.generate import main

if __name__ == '__main__':
    main()
