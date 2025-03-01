from trove_classifiers import classifiers
from distutils.version import LooseVersion as versioner

from requests.compat import quote

from django.conf import settings
from django.db import models


#this is gross, but requests doesn't import quote_plus into compat,
#so we re-implement it here
def quote_plus(s, safe=''):
    """Quote the query fragment of a URL; replacing ' ' with '+'"""
    if ' ' in s:
        s = quote(s, safe + ' ')
        return s.replace(' ', '+')
    return quote(s, safe)


def uniquer(seq, idfun=None):
    if idfun is None:
        def idfun(x):
            return x
    seen = {}
    result = []
    for item in seq:
        marker = idfun(item)
        if marker in seen:
            continue
        seen[marker] = 1
        result.append(item)
    return result


def get_version(package):

    versions = package.version_set.exclude(upload_time=None)
    try:
        return versions.latest()
    except models.ObjectDoesNotExist:
        return None


def get_pypi_version(package):
    versions = []
    for v_str in package.version_set.values_list('number', flat=True):
        v = versioner(v_str)
        comparable = True
        for elem in v.version:
            if isinstance(elem, str):
                comparable = False
        if comparable:
            versions.append(v)
    if versions:
        return str(sorted(versions)[-1])
    return ''


def normalize_license(license):
    """ Handles when:

        * No license is passed
        * Made up licenses are submitted
        * Official PyPI trove classifier licenses
        * Common abbreviations of licenses

    """
    if license is None:
        return "UNKNOWN"
    if license.strip() in classifiers:
        return license.strip()
    if len(license.strip()) > 20:
        return "Custom"
    return license.strip()
