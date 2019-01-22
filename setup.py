#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import find_packages, setup

with open("README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read()

requirements = [
    "aiohttp<3.5.0",
    "click>=7.0",
    "coloredlogs",
    "discord.py[voice]",
    "humanize",
    "plexapi",
    "psutil",
    "sqlalchemy",
    "sxm==0.1.0",
    "tabulate",
]

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
    entry_points={"console_scripts": ["dsxm=discord_siriusxm.cli:main"]},
    install_requires=requirements,
    dependency_links=[
        "https://github.com/Rapptz/discord.py/tarball/rewrite#egg=discord.py",
        "https://github.com/AngellusMortis/SiriusXM/tarball/master#egg=sxm",
    ],
    license="MIT license",
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="discord_siriusxm",
    name="discord_siriusxm",
    packages=find_packages(include=["discord_siriusxm"]),
    setup_requires=setup_requirements,
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/AngellusMortis/discord_siriusxm",
    version="0.1.0",
    zip_safe=False,
)
