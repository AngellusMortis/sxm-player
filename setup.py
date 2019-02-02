#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import find_packages, setup

# for pip >= 10
try:
    from pip._internal.req import parse_requirements
# for pip <= 9.0.3
except ImportError:
    from pip.req import parse_requirements
from setuptools import find_packages, setup

with open("README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read()

req_files = {
    "dev": "reqs/dev.in",
    "requirements": "reqs/requirements.in",
    "setup": "reqs/setup.in",
}

requirements = {}
for req, req_file in req_files.items():
    reqs = parse_requirements(req_file, session="fake")
    requirements[req] = [str(req.req) for req in reqs]

setup_requirements = ["pytest-runner"]

test_requirements = ["pytest"]

setup(
    author="Christopher Bailey",
    author_email="cbailey@mort.is",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    description="A Discord bot that will play SiriusXM radio stations.",
    entry_points={"console_scripts": ["mortis-music=mortis_music.cli:main"]},
    install_requires=requirements["requirements"],
    dependency_links=[
        "https://github.com/Rapptz/discord.py/tarball/rewrite#egg=discord.py",
        "https://github.com/AngellusMortis/SiriusXM/tarball/master#egg=sxm",
    ],
    license="MIT license",
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="mortis_music",
    name="mortis_music",
    packages=find_packages(include=["mortis_music"]),
    setup_requires=requirements["setup"],
    test_suite="tests",
    tests_require=requirements["dev"],
    url="https://github.com/AngellusMortis/mortis_music",
    version="0.1.0",
    zip_safe=False,
    extras_require={"dev": requirements["dev"]},
)
