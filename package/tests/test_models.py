from django.test import TestCase

from package.models import Package, Version
from package.tests import data, initial_data

class VersionTests(TestCase):
    def setUp(self):
        data.load()

    def test_score(self):
        p = Package.objects.get(slug='django-cms')
        # The packages is not picked up as a Python 3 at this stage
        # because django-cms package is added in data.py first,
        # then Versions (where Python3 support flag is) is added after

        self.assertNotEqual(p.score, p.repo_watchers)

        # however, calculating the score will fetch the latest data, and the score = stars
        self.assertEqual(p.calculate_score(), p.repo_watchers)

        # we save / update. Value is saved for grid order
        p.save()
        self.assertEqual(p.score, p.repo_watchers)

    def test_score_abandoned_package(self):
        p = Package.objects.get(slug='django-divioadmin')
        p.save()  # updates the score

        # score should be -100
        # abandoned for 2 years = loss 10% for each 3 months = 80% of the stars
        # + a -30% for not supporting python 3
        self.assertEqual(p.score, -100, p.score)

    def test_score_abandoned_package_10_years(self):
        p = Package.objects.get(slug='django-divioadmin2')
        p.save()  # updates the score
        self.assertLess(p.score, 0, p.score)

    def test_version_order(self):
        p = Package.objects.get(slug='django-cms')
        versions = p.version_set.by_version()
        expected_values = [ '2.0.0',
                            '2.0.1',
                            '2.0.2',
                            '2.1.0',
                            '2.1.1',
                            '2.1.2',
                            '2.1.3']
        returned_values = [v.number for v in versions]
        self.assertEqual(returned_values,expected_values)

    def test_version_license_length(self):
        v = Version.objects.all()[0]
        v.license = "x"*50
        v.save()
        self.assertEqual(v.license,"Custom")

class PackageTests(TestCase):
    def setUp(self):
        initial_data.load()

    def test_license_latest(self):
        for p in Package.objects.all():
            self.assertEqual("UNKNOWN", p.license_latest)
