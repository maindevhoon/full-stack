from pathlib import Path
from tempfile import TemporaryDirectory

from django.db import connections
from django.test.runner import DiscoverRunner


class FileDatabaseTestRunner(DiscoverRunner):
    def run_tests(self, test_labels, **kwargs):
        test_settings = connections["default"].settings_dict["TEST"]
        original_name = test_settings["NAME"]
        with TemporaryDirectory(prefix="canteen-tests-") as folder:
            test_settings["NAME"] = str(Path(folder) / "test.sqlite3")
            try:
                return super().run_tests(test_labels, **kwargs)
            finally:
                test_settings["NAME"] = original_name
