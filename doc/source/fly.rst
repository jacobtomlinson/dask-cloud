Fly.io
======

.. currentmodule:: dask_cloudprovider.fly

.. autosummary::
   FlyMachineCluster

Overview
--------

Authentication
^^^^^^^^^^^^^^

To authenticate with Fly you must first generate a
`personal access token <https://fly.io/user/personal_access_tokens/>`_.

Then you must put this in your Dask configuration at ``cloudprovider.fly.token``. This can be done by
adding the token to your YAML configuration or exporting an environment variable.

.. code-block:: yaml

   # ~/.config/dask/cloudprovider.yaml

   cloudprovider:
     fly:
       token: "yourtoken"

.. code-block:: console

   $ export DASK_CLOUDPROVIDER__FLY__TOKEN="yourtoken"

FlyMachine
----------

.. autoclass:: FlyMachineCluster
   :members:
