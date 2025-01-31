Dask Cloud Provider
===================

*Native Cloud integration for Dask.*

This package contains open source tools to help you deploy and operate Dask clusters on the cloud.
It contains cluster managers which can help you launch clusters using native cloud resources like VMs or containers,
it has tools and plugins for use in ANY cluster running on the cloud and is a great source of documentation for Dask cloud deployments.

It is by no means the "complete" or "only" way to run Dask on the cloud, check out the :doc:`alternatives` page for more tools.

Cluster managers
----------------

This package provides classes for constructing and managing ephemeral Dask clusters on various
cloud platforms.

Dask Cloud Provider is one of many options for deploying Dask clusters, see `Deploying Dask <https://docs.dask.org/en/stable/deploying.html#distributed-computing>`_ in the Dask documentation for an overview of additional options.

To use a cloud provider cluster manager you can import it and instantiate it. Instantiating the class
will result in cloud resources being created for you.

.. code-block:: python

    from dask_cloudprovider.aws import FargateCluster
    cluster = FargateCluster(
        # Cluster manager specific config kwargs
    )

You can then construct a Dask client with that cluster object to use the cluster.

.. code-block:: python

    from dask.distributed import Client
    client = Client(cluster)

Once you are connected to the cluster you can go ahead and use Dask and all computation will take
place on your cloud resource.

Once you are finished be sure to close out your cluster to shut down any cloud resources you have and end any charges.

.. code-block:: python

    cluster.close()

.. warning::

   Cluster managers will attempt to automatically remove hanging cloud resources on garbage collection if the cluster
   object is destroyed without calling ``cluster.close()``, however this is not guaranteed.

To implicitly close your cluster when you are done with it you can optionally contruct the cluster manager via a
context manager. However this will result in the creation and destruction of the whole cluster whenever you run
this code.

.. code-block:: python

    from dask_cloudprovider.aws import FargateCluster
    from dask.distributed import Client

    with FargateCluster(...) as cluster:
        with Client(cluster) as client:
            # Do some Dask things

Plugins
-------

Dask components like Schedulers and Workers can benefit from being cloud-aware.
This project has plugins and tools that extend these components.

One example is having the workers check for termination warnings when running on ephemeral/spot instances and begin migrating data to other workers.

For Azure VMs you could use the :class:`dask_cloudprovider.azure.AzurePreemptibleWorkerPlugin` to do this.
It can be used on any cluster that has workers running on Azure VMs, not just ones created with :class:`dask_cloudprovider.azure.AzureVMCluster`.

.. code-block:: python

    from distributed import Client
    client = Client("<Any Dask cluster running on Azure VMs>")

    from dask_cloudprovider.azure import AzurePreemptibleWorkerPlugin
    client.register_worker_plugin(AzurePreemptibleWorkerPlugin())


.. toctree::
    :maxdepth: 2
    :hidden:
    :caption: Overview

    installation.rst
    config.rst
    alternatives.rst

.. toctree::
    :maxdepth: 2
    :hidden:
    :caption: Providers

    aws.rst
    digitalocean.rst
    fly.rst
    gcp.rst
    azure.rst
    hetzner.rst
    ibm.rst
    openstack.rst
    nebius.rst

.. toctree::
    :maxdepth: 2
    :hidden:
    :caption: Advanced

    troubleshooting.rst
    security.rst
    gpus.rst
    packer.rst

.. toctree::
    :maxdepth: 2
    :hidden:
    :caption: Developer

    testing.rst
    releasing.rst
