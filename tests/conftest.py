import sys, pathlib
# Ensure hooks/ is always on the path for all test modules
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "hooks"))
