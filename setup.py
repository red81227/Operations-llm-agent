"""This file is for setup information and version control used."""
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

with open('README.md') as f:
    readme_text = f.read()

setup(
    project_name='service-operation-agent',
    project_version='0.0.2',
    description='In this project, we will develop LLM application for IOT operation system',
    long_description=readme_text,
    author='Hank Liang',
    url='',
    packages=find_packages(exclude=('tests'))
)
