import os, sys
import os.path

from setuptools import setup, find_packages


root = os.path.abspath(os.path.dirname(__file__))
package_name = "vaccinewatcher"
packages = find_packages(
    include=[package_name, "{}.*".format(package_name)]
)

__version_info__ = (0, 0, 1)
version = ".".join(map(str, __version_info__))
binary_names = ['vaccinewatcher']


with open(os.path.join(root, 'README.md'), 'rb') as readme:
    long_description = readme.read().decode('utf-8')

setup(
    name=package_name,
    version=version,
    description="Monitor Vaccine Availability from your Local CVS and Walgreens (US Only).",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author='Tri Songz',
    author_email='ts@scontentengine.ai',
    url='http://github.com/trisongz/vaccinewatcher',
    python_requires='>3.6',
    install_requires=[
        "selenium",
        "selenium-wire",
        "undetected-chromedriver",
        "elemental"
    ],
    packages=packages,
    entry_points={
        "console_scripts": [
            "vaccinewatcher = vaccinewatcher.watcher:cli",
        ]
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: Developers",
    ],
    data_files=[],
    include_package_data=True
)