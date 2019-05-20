#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import find_packages, setup


def parse_requirements(filename):
    """ load requirements from a pip requirements file """
    lines = (line.strip() for line in open(filename))
    return [line for line in lines if line and not line.startswith("#")]


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
    requirements[req] = parse_requirements(req_file)


setup(
    author="Christopher Bailey",
    author_email="cbailey@mort.is",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    description="A pluggable SXM music player written in Python",
    entry_points={"console_scripts": ["sxm-player=sxm_player.cli:main"]},
    install_requires=requirements["requirements"],
    license="MIT license",
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="sxm,SiriusXM,XM Radio",
    name="sxm_player",
    packages=find_packages(
        include=["sxm_player", "sxm_player.*"], exclude=["*.debug"]
    ),
    setup_requires=requirements["setup"],
    test_suite="tests",
    tests_require=requirements["dev"],
    url="https://github.com/AngellusMortis/sxm-player",
    version="0.1.1",
    zip_safe=False,
    extras_require={"dev": requirements["dev"]},
)
