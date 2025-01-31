import uuid
import dask
import asyncio
import json
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
        env_vars=None,
        extra_bootstrap=None,
        metadata=None,
        restart=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.machine = None
        self.cluster = cluster
        self.config = config
        self.region = region
        self.vm_size = vm_size
        self.cpus = cpus
        self.memory_mb = memory_mb
        self.image = image
        self.gpu_instance = False
        self.bootstrap = True
        self.extra_bootstrap = extra_bootstrap
        self.env_vars = env_vars
        self.metadata = metadata
        self.restart = restart
        self.app_name = self.cluster.app_name
        self.env_vars["DASK_INTERNAL__INHERIT_CONFIG"] = dask.config.serialize(
            dask.config.global_config
        )
        self.api_token = self.cluster.api_token
        self._client = None
        if self.api_token is None:
            raise ValueError("[fly.io] API token must be provided")

    async def create_vm(self):
        machine_config = machines.FlyMachineConfig(
            env=self.env_vars,
            image=self.image,
            metadata=self.metadata,
            restart=self.restart,
            services=[
                machines.FlyMachineConfigServices(
                    ports=[
                        machines.FlyMachineRequestConfigServicesPort(port=8786),
                    ],
                    protocol="tcp",
                    internal_port=8786,
                ),
                machines.FlyMachineConfigServices(
                    ports=[
                        machines.FlyMachineRequestConfigServicesPort(
                            port=80, handlers=["http"]
                        ),
                        machines.FlyMachineRequestConfigServicesPort(
                            port=443, handlers=["http", "tls"]
                        ),
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
            metrics=None,
            processes=[
                machines.FlyMachineConfigProcess(
                    name="app",
                    cmd=self.command,
                    env=self.env_vars,
                )
            ],
        )
        self.machine = await self._fly().create_machine(
            app_name=self.cluster.app_name,  # The name of the new Fly.io app.
            config=machine_config,  # A FlyMachineConfig object containing creation details.
            name=self.name,  # The name of the machine.
            region=self.region,  # The deployment region for the machine.
        )
        self.host = f"{self.machine.id}.vm.{self.cluster.app_name}.internal"
        self.internal_ip = self.machine.private_ip
        self.port = 8786
        self.address = (
            f"{self.cluster.protocol}://[{self.machine.private_ip}]:{self.port}"
        )
        # self.external_address = f"{self.cluster.protocol}://{self.host}:{self.port}"
        log_attributes = {
            "name": self.name,
            "machine": self.machine.id,
            "internal_ip": self.internal_ip,
            "address": self.address,
        }
        if self.external_address is not None:
            log_attributes["external_address"] = self.external_address
        logline = "[fly.io] Created machine " + " ".join(
            [f"{k}={v}" for k, v in log_attributes.items()]
        )
        self.cluster._log(logline)
        return self.address, self.external_address

    async def destroy_vm(self):
        if self.machine is None:
            self.cluster._log(
                "[fly.io] Not Terminating Machine: Machine does not exist"
            )
            return
        await self._fly().delete_machine(
            app_name=self.cluster.app_name,
            machine_id=self.machine.id,
            force=True,
        )
        self.cluster._log(f"[fly.io] Terminated machine {self.name}")

    async def wait_for_scheduler(self):
        self.cluster._log(f"Waiting for scheduler to run at {self.address}")
        while not asyncio.create_task(async_socket_open(self.internal_ip, self.port)):
            await asyncio.sleep(1)
        self.cluster._log("Scheduler is running")
        return True

    async def wait_for_app(self):
        self.cluster._log("[fly.io] Waiting for app to be created...")
        while self.cluster.app_name is None or self.app is None:
            await asyncio.sleep(1)
        return True

    def _fly(self):
        if self._client is None:
            self._client = Fly(api_token=self.api_token)
        return self._client


class FlyMachineScheduler(SchedulerMixin, FlyMachine):
    """Scheduler running on a Fly.io Machine."""

    def __init__(
        self,
        *args,
        scheduler_options: dict = {},
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.name = f"dask-{self.cluster.uuid}-scheduler"
        self.port = scheduler_options.get("port", 8786)
        self.command = [
            "python",
            "-m",
            "distributed.cli.dask_scheduler",
            "--host",
            "fly-local-6pn",
        ] + cli_keywords(scheduler_options, cls=_Scheduler)

    async def start(self):
        self.cluster._log(f"Starting scheduler on {self.name}")
        if self.cluster.app_name is None:
            await self.create_app()
        await self.start_scheduler()
        self.status = Status.running

    async def start_scheduler(self):
        self.cluster._log("Creating scheduler instance")
        address, external_address = await self.create_vm()
        await self.wait_for_scheduler()
        self.cluster._log(f"Scheduler running at {address}")
        self.cluster.scheduler_internal_address = address
        self.cluster.scheduler_external_address = external_address
        self.cluster.scheduler_port = self.port

    async def close(self):
        await super().close()
        if self.cluster.app_name is not None:
            await self.delete_app()

    async def create_app(self):
        """Create a Fly.io app."""
        if self.cluster.app_name is not None:
            self.cluster._log("[fly.io] Not creating app as it already exists")
            return
        app_name = f"dask-{str(uuid.uuid4())[:8]}"
        try:
            self.cluster._log(f"[fly.io] Trying to create app {app_name}")
            self.app = await self._fly().create_app(app_name=app_name)
            self.cluster._log(f"[fly.io] Created app {app_name}")
            self.cluster.app_name = app_name
        except Exception as e:
            self.cluster._log(f"[fly.io] Failed to create app {app_name}")
            self.app = "failed"
            raise e

    async def delete_app(self):
        """Delete a Fly.io app."""
        if self.cluster.app_name is None:
            self.cluster._log("[fly.io] Not deleting app as it does not exist")
            return
        await self._fly().delete_app(app_name=self.cluster.app_name)
        self.cluster._log(f"[fly.io] Deleted app {self.cluster.app_name}")

    async def wait_for_app(self):
        """Wait for the Fly.io app to be ready."""
        while self.app is None or self.cluster.app_name is None:
            self.cluster._log("[fly.io] Waiting for app to be created")
            await asyncio.sleep(1)


class FlyMachineWorker(WorkerMixin, FlyMachine):
    """Worker running on a Fly.io Machine."""

    def __init__(
        self,
        *args,
        worker_module: str = None,
        worker_class: str = None,
        worker_options: dict = {},
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if worker_module is not None:
            self.worker_module = worker_module
            self.command = [
                "python",
                "-m",
                self.worker_module,
                self.scheduler,
                "--name",
                str(self.name),
            ] + cli_keywords(worker_options, cls=_Worker, cmd=self.worker_module)
        if worker_class is not None:
            self.worker_class = worker_class
            self.command = [
                "python",
                "-m",
                "distributed.cli.dask_spec",
                self.scheduler,
                "--spec",
                json.dumps(
                    {
                        "cls": self.worker_class,
                        "opts": {
                            **worker_options,
                            "name": self.name,
                            "host": "fly-local-6pn",
                        },
                    }
                ),
            ]


class FlyMachineCluster(VMCluster):
    """Cluster running on Fly.io Machines.

    VMs in Fly.io (FLY) are referred to as machines. This cluster manager constructs a Dask cluster
    running on VMs.

    .. note::
        By default, the cluster will instantiate a new Fly.io app. The app will be deleted when
        the cluster is closed. If you want to use an existing app, you can pass the app name to the
        ``app_name`` parameter.

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
        be created automatically. Default is ``False``.
    debug : bool, optional
        More information will be printed when constructing clusters to enable debugging.

    Examples
    --------

    Create the cluster.

    >>> from dask_cloudprovider.fly import FlyMachineCluster
    >>> cluster = FlyMachineCluster(n_workers=1)
    Starting scheduler on dask-e058d78e-scheduler
    [fly.io] Trying to create app dask-122f0e5f
    [fly.io] Created app dask-122f0e5f
    Creating scheduler instance
    [fly.io] Created machine name=dask-e058d78e-scheduler id=6e82d4e6a02d58
    Waiting for scheduler to run at 6e82d4e6a02d58.vm.dask-122f0e5f.internal:8786
    Scheduler is running
    Scheduler running at tcp://[fdaa:1:53b:a7b:112:2bed:ccd1:2]:8786
    Creating worker instance
    [fly.io] Created machine name=dask-e058d78e-worker-7b24cb61 id=32873e0a095985

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
    [fly.io] Terminated machine dask-e058d78e-worker-7b24cb61
    [fly.io] Terminated machine dask-e058d78e-scheduler
    [fly.io] Deleted app dask-122f0e5f

    You can also do this all in one go with context managers to ensure the cluster is
    created and cleaned up.

    >>> with FlyMachineCluster(n_workers=1) as cluster:
    ...     with Client(cluster) as client:
    ...         print(da.random.random((1000, 1000), chunks=(100, 100)).mean().compute())
    Starting scheduler on dask-e058d78e-scheduler
    [fly.io] Trying to create app dask-122f0e5f
    [fly.io] Created app dask-122f0e5f
    Creating scheduler instance
    [fly.io] Created machine name=dask-e058d78e-scheduler id=6e82d4e6a02d58
    Waiting for scheduler to run at 6e82d4e6a02d58.vm.dask-122f0e5f.internal:8786
    Scheduler is running
    Scheduler running at tcp://[fdaa:1:53b:a7b:112:2bed:ccd1:2]:8786
    Creating worker instance
    [fly.io] Created machine name=dask-e058d78e-worker-7b24cb61 id=32873e0a095985
    0.5000558682356162
    [fly.io] Terminated machine dask-e058d78e-worker-7b24cb61
    [fly.io] Terminated machine dask-e058d78e-scheduler
    [fly.io] Deleted app dask-122f0e5f

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
        self.app_name = app_name
        self._client = None
        self.options = {
            "cluster": self,
            "config": self.config,
            "region": region if region is not None else self.config.get("region"),
            "vm_size": vm_size if vm_size is not None else self.config.get("vm_size"),
            "image": image if image is not None else self.config.get("image"),
            "token": token if token is not None else self.config.get("token"),
            "memory_mb": memory_mb
            if memory_mb is not None
            else self.config.get("memory_mb"),
            "cpus": cpus if cpus is not None else self.config.get("cpus"),
            "app_name": self.app_name,
            "protocol": self.config.get("protocol", "tcp"),
            "security": self.config.get("security", False),
            "host": "fly-local-6pn",
        }
        self.scheduler_options = {**self.options}
        self.worker_options = {**self.options}
        self.api_token = self.options["token"]
        super().__init__(debug=debug, security=self.options["security"], **kwargs)
