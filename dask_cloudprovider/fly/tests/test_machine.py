import pytest

import dask

# sdk = pytest.importorskip(".sdk")

from dask_cloudprovider.fly.machine import FlyMachineCluster
from dask.distributed import Client
from distributed.core import Status


async def skip_without_credentials(config):
    if config.get("token") is None:
        pytest.skip(
            """
        You must configure a Fly.io API token to run this test.

        Either set this in your config

            # cloudprovider.yaml
            cloudprovider:
              fly:
                token: "yourtoken"

        Or by setting it as an environment variable

            export DASK_CLOUDPROVIDER__FLY__TOKEN="yourtoken"

        """
        )


@pytest.fixture
async def config():
    return dask.config.get("cloudprovider.fly", {})


@pytest.fixture
@pytest.mark.external
async def cluster(config):
    await skip_without_credentials(config)
    async with FlyMachineCluster(asynchronous=True) as cluster:
        yield cluster


@pytest.mark.asyncio
@pytest.mark.external
async def test_init():
    cluster = FlyMachineCluster(asynchronous=True)
    assert cluster.status == Status.created


@pytest.mark.asyncio
@pytest.mark.timeout(600)
@pytest.mark.external
async def test_create_cluster(cluster):
    assert cluster.status == Status.running

    cluster.scale(1)
    await cluster
    assert len(cluster.workers) == 1

    async with Client(cluster, asynchronous=True) as client:

        def inc(x):
            return x + 1

        assert await client.submit(inc, 10).result() == 11


# @pytest.mark.asyncio
# async def test_get_cloud_init():
#     cloud_init = FlyMachineCluster.get_cloud_init(
#         docker_args="--privileged",
#     )
#     assert " --privileged " in cloud_init
