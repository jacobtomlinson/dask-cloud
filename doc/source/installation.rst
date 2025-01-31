Installation
============

Pip
---

.. code-block:: console

   $ pip install dask-cloudprovider[all]

You can also restrict your install to just a specific cloud provider by giving their name instead of ``all``.

.. code-block:: console

   $ pip install dask-cloudprovider[aws]  # or
   $ pip install dask-cloudprovider[azure]  # or
   $ pip install dask-cloudprovider[azureml]  # or
   $ pip install dask-cloudprovider[digitalocean]  # or
   $ pip install dask-cloudprovider[fly]  # or
   $ pip install dask-cloudprovider[gcp]  # or
   $ pip install dask-cloudprovider[ibm]  # or
   $ pip install dask-cloudprovider[openstack]  # or
   $ pip install dask-cloudprovider[nebius]

Conda
-----

.. code-block:: console

   $ conda install -c conda-forge dask-cloudprovider
