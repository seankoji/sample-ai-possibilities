# Coverage

The existing unified runner executes isolated subprocesses. Coverage.py's subprocess patch records those child processes and `coverage combine` merges them before XML export.

From this directory:

```sh
python -m pip install coverage==7.16.1
python -m coverage run run_tests.py --integration
python -m coverage combine
python -m coverage xml
```

`coverage/coverage.xml` is Cobertura XML. The measured scope is the shared library and diamond team runtime. Test helpers and test scripts are excluded. Deployment scripts and other upstream examples are outside this report's scope. CI retains reports for each Python version without imposing a coverage threshold.
