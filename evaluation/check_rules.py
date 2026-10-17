"""Run rules tests and optional supplied-inference integration without pytest."""
import argparse
import importlib
import inspect
import json
from pathlib import Path
import unittest


class CountedResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.subtests_run=0
    def addSubTest(self,test,subtest,err):
        self.subtests_run+=1
        super().addSubTest(test,subtest,err)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--with-inference',action='store_true')
    args=parser.parse_args()
    legacy=0
    for module_name in ('app.rules.test_classifier','evaluation.test_rules','evaluation.test_run_rules'):
        for name,test in inspect.getmembers(importlib.import_module(module_name),inspect.isfunction):
            if name.startswith('test_'):
                test();legacy+=1
    names=['evaluation.test_decision','evaluation.test_ai4_rules','evaluation.test_ai4_integration',
           'evaluation.test_temporal']
    if args.with_inference:
        import app.inference
        source=Path(app.inference.__file__).parent
        names.extend('app.inference.'+path.stem for path in sorted(source.glob('test_*.py')))
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    result=unittest.TextTestRunner(verbosity=1,resultclass=CountedResult).run(suite)
    print(json.dumps({'tests':legacy+result.testsRun,'subtests':result.subtests_run,
                      'skipped':len(result.skipped),'success':result.wasSuccessful()}))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    raise SystemExit(main())
