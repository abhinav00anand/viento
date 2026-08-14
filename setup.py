#!/usr/bin/env python3
"""
Setup script for viento.
Provides setuptools compatibility for editable installs and legacy tooling.
"""
from setuptools import setup, find_packages

if __name__ == "__main__":
    setup(
        name="viento",
        version="0.1.0",
        packages=find_packages(include=["viento", "viento.*"]),
        entry_points={
            "console_scripts": [
                "zephyr=viento.cli.main:cli",
            ],
        },
    )
