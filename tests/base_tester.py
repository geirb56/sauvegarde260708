import logging
import unittest

class BaseTester(unittest.TestCase):
    """
    Base class for all test cases, providing common functionality
    for error handling, logging, and utilities.
    """

    @classmethod
    def setUpClass(cls):
        """Set up the logger for the test class."""
        cls.logger = logging.getLogger(cls.__name__)
        logging.basicConfig(level=logging.INFO)

    def setUp(self):
        """Common setup that runs before each test."""
        self.logger.info("Starting test: %s", self._testMethodName)

    def tearDown(self):
        """Common cleanup that runs after each test."""
        self.logger.info("Finished test: %s", self._testMethodName)

    def assert_no_errors(self, result):
        """Utility method to assert no errors in the test result."""
        if result.errors or result.failures:
            self.logger.error("Test failed with errors: %s", result.errors + result.failures)
            self.fail("Test has errors or failures.")

    def log_test_case(self, message):
        """Log a custom message related to the test case."""
        self.logger.info(message)

    @staticmethod
    def utility_method(arg1, arg2):
        """A utility method for common tests."""
        return arg1 + arg2

