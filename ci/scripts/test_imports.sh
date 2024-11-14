#!/usr/bin/env bash
set -o errexit


test_import () {
    echo "Create environment: python=3.12 $1"
    # Create an empty environment
    conda create -q -y -n test-imports -c conda-forge python=3.12
    conda activate test-imports
    pip install -e .[$1]
    echo "python -c '$2'"
    python -c "$2"
    echo "Success [$1] 🚀"
    conda deactivate
    conda env remove -n test-imports
}

test_import "aws"               "import dask_cloudprovider.aws"
test_import "azure"             "import dask_cloudprovider.azure"
test_import "digitalocean"      "import dask_cloudprovider.digitalocean"
test_import "gcp"               "import dask_cloudprovider.gcp"
test_import "fly"               "import dask_cloudprovider.fly"
test_import "ibm"               "import dask_cloudprovider.ibm"
test_import "openstack"         "import dask_cloudprovider.openstack"
