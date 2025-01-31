#!/usr/bin/env python

from os.path import exists
from setuptools import setup, find_packages

import versioneer

extras_require = {
    "aws": ["aiobotocore>=0.10.2"],
    "azure": [
        "azure-mgmt-compute>=18.0.0",
        "azure-mgmt-network>=16.0.0",
        "azure-identity",
    ],
    "digitalocean": ["python-digitalocean>=1.15.0"],
    "gcp": ["google-api-python-client>=1.12.5", "google-auth>=1.23.0"],
    "hetzner": ["hcloud>=1.10.0"],
    "fly": ["httpx>=0.24.0", "pydantic>=1.10.7"],
    "ibm": ["ibm_code_engine_sdk>=3.1.0"],
    "openstack": ["openstacksdk>=3.3.0"],
    "nebius": ["nebius>=0.2.0"],
}
extras_require["all"] = set(pkg for pkgs in extras_require.values() for pkg in pkgs)

setup(
    name="dask-cloudprovider",
    cmdclass=versioneer.get_cmdclass(),
    version=versioneer.get_version(),
    description="Native Cloud Provider integration for Dask",
    url="https://github.com/dask/dask-cloudprovider",
    keywords="dask,cloud,distributed",
    license="BSD",
    packages=find_packages(),
    include_package_data=True,
    long_description=(open("README.rst").read() if exists("README.rst") else ""),
    long_description_content_type="text/x-rst",
    zip_safe=False,
    install_requires=list(open("requirements.txt").read().strip().split("\n")),
    extras_require=extras_require,
    entry_points="""
    [console_scripts]
    dask-ecs=dask_cloudprovider.cli.ecs:go
    """,
    python_requires=">=3.10",
)
