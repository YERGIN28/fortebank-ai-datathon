"""Run the team's unittest suites and legacy function tests without pytest."""
import importlib
import inspect
from pathlib import Path
import unittest


def main():
    count = 0
    for name in ("app.rules.test_classifier", "evaluation.test_rules", "evaluation.test_run_rules"):
        module = importlib.import_module(name)
        for name, test in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("test_"):
                test()
                count += 1
    root = Path(__file__).resolve().parents[1]
    names = ["evaluation.test_decision", "evaluation.test_integration"]
    names.extend("app.inference." + path.stem for path in sorted((root / "app/inference").glob("test_*.py")))
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"Total: {count + result.testsRun}; legacy: {count}; unittest: {result.testsRun}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
