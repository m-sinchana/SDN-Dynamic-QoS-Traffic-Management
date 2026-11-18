#!/usr/bin/env python3
"""
Master Test Runner for SDN Dynamic QoS Traffic Management System
Executes all test suites:
  1. Low-Level Sockets & Protocol Serialization (tests/test_sockets.py)
  2. Controller Classification & Dynamic State Machine (tests/test_controller_logic.py)
  3. Experiment Analytics & Fairness Pipeline (tests/test_experiment_pipeline.py)
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def main():
    test_loader = unittest.TestLoader()
    test_suite = unittest.TestSuite()

    # Discover tests in tests/
    tests_dir = os.path.dirname(__file__)
    discovered_suite = test_loader.discover(start_dir=tests_dir, pattern="test_*.py")
    test_suite.addTests(discovered_suite)

    print("\n" + "=" * 80)
    print(" RUNNING COMPLETE AUTOMATED TEST SUITE (SDN QoS SYSTEM)")
    print("=" * 80)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)

    print("=" * 80)
    if result.wasSuccessful():
        print(f" [PASS] ALL {result.testsRun} TESTS PASSED CLEANLY!")
        print("=" * 80 + "\n")
        sys.exit(0)
    else:
        print(f" [FAIL] {len(result.failures)} FAILURES, {len(result.errors)} ERRORS")
        print("=" * 80 + "\n")
        sys.exit(1)


if __name__ == '__main__':
    main()
