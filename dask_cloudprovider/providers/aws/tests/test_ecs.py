import pytest

aiobotocore = pytest.importorskip("aiobotocore")


def test_import():
    from dask_cloudprovider import ECSCluster  # noqa
    from dask_cloudprovider import FargateCluster  # noqa
