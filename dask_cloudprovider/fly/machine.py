import uuid
import dask
import asyncio
import warnings
from dask_cloudprovider.generic.vmcluster import (
    VMCluster,
    VMInterface,
    SchedulerMixin,
    WorkerMixin,
)
from distributed.core import Status
from distributed.worker import Worker as _Worker
from distributed.scheduler import Scheduler as _Scheduler
from distributed.utils import cli_keywords
from dask_cloudprovider.utils.socket import async_socket_open

try:
    from .sdk.models import machines
    from .sdk.fly import Fly
except ImportError as e:
    msg = (
        "Dask Cloud Provider Fly.io requirements are not installed.\n\n"
        "Please pip install as follows:\n\n"
        '  pip install "dask-cloudprovider[fly]" --upgrade  # or python -m pip install'
    )
    raise ImportError(msg) from e


# logger = logging.getLogger(__name__)

class FlyMachine(VMInterface):
    def __init__(
        self,
        cluster: str,
        config,
        *args,
        region: str = None,
        vm_size: str = None,
        memory_mb: int = None,
        cpus: int = None,
        image: str = None,
        env_vars = None,
        extra_bootstrap = None,
        metadata = None,
        restart = None,
        **kwargs,
    ):
        print("machine args: ")
        print(args)
        print("machine kwargs: ")
        print(kwargs)
        super().__init__(*args, **kwargs)
        self.machine = None
        self.cluster = cluster
        self.config = config
        self.region = region
        self.vm_size = vm_size
        self.cpus = 1
        self.memory_mb = 1024
        self.image = image
        self.gpu_instance = False
        self.bootstrap = True
        self.extra_bootstrap = extra_bootstrap
        self.env_vars = env_vars
        self.metadata = metadata
        self.restart = restart
        self.app_name = self.cluster.app_name
        self.set_env = 'DASK_INTERNAL__INHERIT_CONFIG="{}"'.format(
            dask.config.serialize(dask.config.global_config)
        )
        # We need the token
        self.api_token = self.cluster.api_token
        if self.api_token is None:
            raise ValueError("Fly.io API token must be provided")
        # set extra images
        if "EXTRA_PIP_PACKAGES" in self.env_vars:
            self.env_vars["EXTRA_PIP_PACKAGES"] += "dask[distributed]"
        else:
            self.env_vars["EXTRA_PIP_PACKAGES"] = " dask[distributed]"

    async def create_vm(self):
        machine_config = machines.FlyMachineConfig(
            env=self.env_vars,
            # init=machines.FlyMachineConfigInit(
            #     cmd=self.command,
            # ),
            image=self.image,
            metadata=self.metadata,
            restart=self.restart,
            services=[
                machines.FlyMachineConfigServices(
                    ports=[
                        machines.FlyMachineRequestConfigServicesPort(
                            port=80, handlers=["http"]
                        ),
                        machines.FlyMachineRequestConfigServicesPort(
                            port=443, handlers=["http", "tls"]
                        ),
                        machines.FlyMachineRequestConfigServicesPort(
                            port=8786, handlers=["http", "tls"]
                        ),
                    ],
                    protocol="tcp",
                    internal_port=8786,
                ),
                machines.FlyMachineConfigServices(
                    ports=[
                        machines.FlyMachineRequestConfigServicesPort(
                            port=8787, handlers=["http", "tls"]
                        ),
                    ],
                    protocol="tcp",
                    internal_port=8787,
                ),
            ],
            guest=machines.FlyMachineConfigGuest(
                cpu_kind="shared",
                cpus=self.cpus,
                memory_mb=self.memory_mb,
            ),
            size=self.vm_size,
            metrics=None,
            processes=[
                machines.FlyMachineConfigProcess(
                    name="app",
                    cmd=[self.command],
                    env=self.env_vars,
                    user="root",
                    # entrypoint=["tini", "-g", "--", "/usr/bin/prepare.sh"]
                    # entrypoint=["/bin/bash", "/usr/bin/prepare.sh"]
                    entrypoint=["/bin/bash", "-c"]
                )
            ],
        )
        await self.wait_for_app()
        self.machine = await self.cluster._fly().create_machine(
            app_name=self.cluster.app_name,  # The name of the new Fly.io app.
            config=machine_config,  # A FlyMachineConfig object containing creation details.
            name=self.name,  # The name of the machine.
            region=self.region,  # The deployment region for the machine.
        )
        self.cluster._log(f"Created machine {self.name}")
        self.address = f'tcp://[{self.machine.private_ip}]:8786'
        # self.external_address = f'tls://{self.cluster.app_name}.fly.dev:443'
        self.host = f'{self.machine.id}.vm.{self.cluster.app_name}.internal'
        self.internal_ip = self.machine.private_ip
        self.port = 8786
        # self.address = f'tcp://{self.host}:{self.port}'
        # self.cluster._log("FlyMachine.create_vm END")
        return self.address, self.external_address
    
    async def destroy_vm(self):
        if self.machine is None:
            self.cluster._log("Not Terminating Machine: Machine does not exist")
            return
        await self.cluster._fly().delete_machine(
            app_name=self.cluster.app_name,
            machine_id=self.machine.id,
            force=True,
        )
        self.cluster._log(f"Terminated machine {self.name}")

    async def wait_for_scheduler(self):
        self.cluster._log(f"Waiting for scheduler to run at {self.host}:{self.port}")
        while not asyncio.create_task(async_socket_open(self.host, self.port)):
            await asyncio.sleep(1)
        # self.cluster._log("Scheduler is running")
    
    async def wait_for_app(self):
        self.cluster._log("FlyMachine.wait_for_app")
        while self.cluster.app_name is None or self.cluster.app is None:
            self.cluster._log("Waiting for app to be created...")
            await asyncio.sleep(1)
        # self.cluster._log("FlyMachine.wait_for_app END")

class FlyMachineScheduler(SchedulerMixin, FlyMachine):
    """Scheduler running on a Fly.io Machine."""

    def __init__(
        self,
        *args,
        scheduler_options: dict = {},
        **kwargs,
    ):
        print("scheduler args: ")
        print(args)
        print("scheduler kwargs: ")
        print(kwargs)
        super().__init__(*args, **kwargs)
        self.name = f"dask-{self.cluster.uuid}-scheduler"
        self.port = scheduler_options.get("port", 8786)
        self.command = " ".join(
            [
                self.set_env,
                "dask",
                "scheduler"
            ]
            + cli_keywords(scheduler_options, cls=_Scheduler)
        )

    async def start(self):
        self.cluster._log(f"Starting scheduler on {self.name}")
        if self.cluster.app is None:
            await self.cluster.create_app()
        await self.cluster.wait_for_app()
        await self.start_scheduler()
        self.status = Status.running
        # self.cluster._log("FlyMachineScheduler.start END")
    
    async def start_scheduler(self):
        self.cluster._log("Creating scheduler instance")
        address, external_address = await self.create_vm()
        await self.wait_for_scheduler()
        self.cluster._log(f"Scheduler running at {address}")
        self.cluster.scheduler_internal_address = address
        self.cluster.scheduler
        # self.cluster.scheduler_external_address = external_address
        self.cluster.scheduler_port = self.port
        # self.cluster._log("FlyMachineScheduler.start_scheduler END")


class FlyMachineWorker(WorkerMixin, FlyMachine):
    """Worker running on a Fly.io Machine."""

    def __init__(
        self,
        scheduler: str,
        cluster: str,
        *args,
        worker_class: str = "FlyMachineScheduler",
        worker_options: dict = {},
        **kwargs,
    ):
        print("worker args: ")
        print(args)
        print("worker kwargs: ")
        print(kwargs)
        super().__init__(scheduler=scheduler, cluster=cluster, **kwargs)
        self.scheduler = scheduler
        self.cluster = cluster
        self.worker_class = worker_class
        self.name = f"dask-{self.cluster.uuid}-worker-{str(uuid.uuid4())[:8]}"
        self.command = " ".join(
            [
                self.set_env,
                "dask",
                "worker",
                self.scheduler,
            ]
            + cli_keywords(worker_options, cls=_Worker),
        )

    async def start(self):
        self.cluster._log("FlyMachineWorker.start")
        await super().start()
        await self.start_worker()

    async def start_worker(self):
        self.cluster._log("Creating worker instance")
        self.address, self.external_address = await self.create_vm()
        # self.address = self.internal_ip

class FlyMachineCluster(VMCluster):
    """Cluster running on Fly.io Machines.

    VMs in Fly.io (FLY) are referred to as machines. This cluster manager constructs a Dask cluster
    running on VMs.

    When configuring your cluster you may find it useful to install the ``flyctl`` tool for querying the
    CLY API for available options.

    https://fly.io/docs/hands-on/install-flyctl/

    Parameters
    ----------
    region: str
        The FLY region to launch your cluster in. A full list can be obtained with ``flyctl platform regions``.
    vm_size: str
        The VM size slug. You can get a full list with ``flyctl platform sizes``.
        The default is ``shared-cpu-1x`` which is 256GB RAM and 1 vCPU
    image: str
        The Docker image to run on all instances.

        This image must have a valid Python environment and have ``dask`` installed in order for the
        ``dask-scheduler`` and ``dask-worker`` commands to be available. It is recommended the Python
        environment matches your local environment where ``FlyMachineCluster`` is being created from.

        By default the ``ghcr.io/dask/dask:latest`` image will be used.
    worker_module: str
        The Dask worker module to start on worker VMs.
    n_workers: int
        Number of workers to initialise the cluster with. Defaults to ``0``.
    worker_module: str
        The Python module to run for the worker. Defaults to ``distributed.cli.dask_worker``
    worker_options: dict
        Params to be passed to the worker class.
        See :class:`distributed.worker.Worker` for default worker class.
        If you set ``worker_module`` then refer to the docstring for the custom worker class.
    scheduler_options: dict
        Params to be passed to the scheduler class.
        See :class:`distributed.scheduler.Scheduler`.
    extra_bootstrap: list[str] (optional)
        Extra commands to be run during the bootstrap phase.
    env_vars: dict (optional)
        Environment variables to be passed to the worker.
    silence_logs: bool
        Whether or not we should silence logging when setting up the cluster.
    asynchronous: bool
        If this is intended to be used directly within an event loop with
        async/await
    security : Security or bool, optional
        Configures communication security in this cluster. Can be a security
        object, or True. If True, temporary self-signed credentials will
        be created automatically. Default is ``True``.
    debug: bool, optional
        More information will be printed when constructing clusters to enable debugging.

    Examples
    --------

    Create the cluster.

    >>> from dask_cloudprovider.fly import FlyMachineCluster
    >>> cluster = FlyMachineCluster(n_workers=1)
    Creating scheduler instance
    Created machine dask-38b817c1-scheduler
    Waiting for scheduler to run
    Scheduler is running
    Creating worker instance
    Created machine dask-38b817c1-worker-dc95260d

    Connect a client.

    >>> from dask.distributed import Client
    >>> client = Client(cluster)

    Do some work.

    >>> import dask.array as da
    >>> arr = da.random.random((1000, 1000), chunks=(100, 100))
    >>> arr.mean().compute()
    0.5001550986751964

    Close the cluster

    >>> client.close()
    >>> cluster.close()
    Terminated machine dask-38b817c1-worker-dc95260d
    Terminated machine dask-38b817c1-scheduler

    You can also do this all in one go with context managers to ensure the cluster is
    created and cleaned up.

    >>> with FlyMachineCluster(n_workers=1) as cluster:
    ...     with Client(cluster) as client:
    ...         print(da.random.random((1000, 1000), chunks=(100, 100)).mean().compute())
    Creating scheduler instance
    Created machine dask-48efe585-scheduler
    Waiting for scheduler to run
    Scheduler is running
    Creating worker instance
    Created machine dask-48efe585-worker-5181aaf1
    0.5000558682356162
    Terminated machine dask-48efe585-worker-5181aaf1
    Terminated machine dask-48efe585-scheduler

    """

    def __init__(
        self,
        region: str = None,
        vm_size: str = None,
        image: str = None,
        token: str = None,
        memory_mb: int = None,
        cpus: int = None,
        debug: bool = False,
        app_name: str = None,
        **kwargs,
    ):
        self.config = dask.config.get("cloudprovider.fly", {})
        self.scheduler_class = FlyMachineScheduler
        self.worker_class = FlyMachineWorker
        self.debug = debug
        self.app = None
        self.app_name = app_name
        self._client = None
        self.options = {
            "cluster": self,
            "config": self.config,
            "region": region if region is not None else self.config.get("region"),
            "vm_size": vm_size if vm_size is not None else self.config.get("vm_size"),
            "image": image if image is not None else self.config.get("image"),
            "token": token if token is not None else self.config.get("token"),
            "memory_mb": memory_mb if memory_mb is not None else self.config.get("memory_mb"),
            "cpus": cpus if cpus is not None else self.config.get("cpus"),
            "app_name": self.app_name,
            "protocol": self.config.get("protocol", "tcp"),
            "security": self.config.get("security", False),
            "host": "fly-local-6pn",
            "security": self.config.get("security", False),
        }
        self.scheduler_options = {
            **self.options,
        }
        self.worker_options = {**self.options}
        self.api_token = self.options["token"]
        super().__init__(
            debug=debug,
            # worker_options=self.worker_options,
            # scheduler_options=self.scheduler_options,
            security=self.options["security"],
            **kwargs
        )

    def _fly(self):
        if self._client is None:
            self._client = Fly(api_token=self.api_token)
        return self._client

    async def create_app(self):
        """Create a Fly.io app."""
        if self.app_name is not None:
            warnings.warn("Not creating app as it already exists")
            return
        app_name = f"dask-{str(uuid.uuid4())[:8]}"
        try:
            warnings.warn(f"trying to create app {app_name}")
            self.app = await self._fly().create_app(app_name=app_name)
            warnings.warn(f"Created app {app_name}")
            self.app_name = app_name
        except Exception as e:
            warnings.warn(f"Failed to create app {app_name}")
            self.app = "failed"
            # self.app_name = "failed"
            raise e

    async def delete_app(self):
        """Delete a Fly.io app."""
        if self.app_name is None:
            warnings.warn("Not deleting app as it does not exist")
            return
        await self._fly().delete_app(app_name=self.app_name)
        warnings.warn(f"Deleted app {self.app_name}")

    async def wait_for_app(self):
        """Wait for the Fly.io app to be ready."""
        while self.app is None or self.app_name is None:
            warnings.warn("Waiting for app to be created")
            await asyncio.sleep(1)