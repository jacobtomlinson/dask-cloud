import dask
from dask_cloudprovider.config import ClusterConfig
import dask.config
import uuid
import json
import shlex

from dask_cloudprovider.generic.vmcluster import (
    VMCluster,
    VMInterface,
    SchedulerMixin,
    WorkerMixin,
)
import time
from distributed.core import Status
from distributed.security import Security

try:
    from ibm_code_engine_sdk.code_engine_v2 import CodeEngineV2
    from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
    from ibm_code_engine_sdk.ibm_cloud_code_engine_v1 import IbmCloudCodeEngineV1
except ImportError as e:
    msg = (
        "Dask Cloud Provider IBM requirements are not installed.\n\n"
        "Please either conda or pip install as follows:\n\n"
        "  conda install -c conda-forge dask-cloudprovider       # either conda install\n"
        '  pip install "dask-cloudprovider[ibm]" --upgrade       # or python -m pip install'
    )
    raise ImportError(msg) from e


class IBMCodeEngine(VMInterface):
    def __init__(
        self,
        cluster: str,
        config,
        image: str = None,
        region: str = None,
        project_id: str = None,
        api_key: str = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.cluster = cluster
        self.config = config
        self.image = image
        self.region = region
        self.project_id = project_id
        self.api_key = api_key
        
        authenticator = IAMAuthenticator(self.api_key, url='https://iam.cloud.ibm.com')
        authenticator.set_disable_ssl_verification(True)  # Disable SSL verification for the authenticator

        self.code_engine_service = CodeEngineV2(authenticator=authenticator)
        self.code_engine_service.set_service_url('https://api.' + self.region + '.codeengine.cloud.ibm.com/v2')
        self.code_engine_service.set_disable_ssl_verification(True)  # Disable SSL verification for the service instance

    async def create_vm(self):
        if type(self.command) is not list:
            components = self.command.split()
            python_command = ' '.join(components[components.index(next(filter(lambda x: x.startswith('python'), components))):])
            python_command += ' --protocol ws,tcp --port 8786,8001'
            python_command = python_command.split()
        
            print("Creating scheduler: ", self.name)

            response = self.code_engine_service.create_app(
                project_id=self.project_id,
                image_reference=self.image,
                name=self.name,
                run_commands=python_command,
                image_port=8786,
                scale_ephemeral_storage_limit="1G",
                scale_cpu_limit="0.25",
                scale_min_instances=1,
                scale_memory_limit="1G",
                run_env_variables=[
                    {
                        "type": "literal",
                        "name": "DASK_INTERNAL_INHERIT_CONFIG",
                        "key": "DASK_INTERNAL_INHERIT_CONFIG",
                        "value": dask.config.serialize(dask.config.global_config),
                    }
                ]
            )
            app = response.get_result()

            # This loop is to wait until the app is ready, it is necessary to get the internal/external URL
            while True:
                response = self.code_engine_service.get_app(
                    project_id=self.project_id,
                    name=self.name,
                )
                app = response.get_result()
                if app["status"] == "ready":
                    break
                
                time.sleep(1)

            print("JOB RUNNING")
            print(app['name'])

            internal_url = app["endpoint_internal"].split("//")[1]
            public_url = app["endpoint"].split("//")[1]

            return internal_url, public_url

        else:
            python_command = self.command

            print("Creating worker: ", self.name)

            self.code_engine_service.create_config_map(
                project_id=self.project_id,
                name=self.name,
                data={
                    "DASK_INTERNAL_INHERIT_CONFIG": dask.config.serialize(dask.config.global_config),
                }
            )

            response = self.code_engine_service.create_job_run(
                project_id=self.project_id,
                image_reference=self.image,
                name=self.name,
                run_commands=python_command,
                scale_ephemeral_storage_limit="1G",
                scale_cpu_limit="0.25",
                scale_memory_limit="1G",
                run_env_variables=[
                    {
                        "type": "config_map_key_reference",
                        "reference": self.name,
                        "name": "DASK_INTERNAL_INHERIT_CONFIG",
                        "key": "DASK_INTERNAL_INHERIT_CONFIG",
                    }
                ]
            )
            app = response.get_result()

            return None, None
        

    async def destroy_vm(self):
        if "worker" in self.name:
            response = self.code_engine_service.delete_job_run(
                project_id=self.project_id,
                name=self.name,
            )
        else:
            response = self.code_engine_service.delete_app(
                project_id=self.project_id,
                name=self.name,
            )
        
        print("DELETED: ", self.name)


# To connect you have to do it to the address my-app.1i6kkczwe7b5.eu-de.codeengine.appdomain.cloud without specifying port, or specifying 443 for https or 80 for http
class IBMCodeEngineScheduler(SchedulerMixin, IBMCodeEngine):
    """Scheduler running in a GCP instance."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def start(self):
        self.cluster.protocol = "wss"
        self.port = 443
        await self.start_scheduler()

    async def start_scheduler(self):
        self.cluster._log(
            f"Launching cluster with the following configuration: "
            f"\n  Source Image: {self.image} "
            f"\n  Region: {self.region} "
            f"\n  Project id: {self.project_id} "
        )
        self.cluster._log("Creating scheduler instance")
        self.internal_ip, self.external_ip = await self.create_vm()
        self.address = f"{self.cluster.protocol}://{self.external_ip}:{self.port}"
        
        await self.wait_for_scheduler()

        self.cluster.scheduler_internal_ip = self.internal_ip
        self.cluster.scheduler_external_ip = self.external_ip
        self.cluster.scheduler_port = self.port
        self.status = Status.running

class IBMCodeEngineWorker(WorkerMixin, IBMCodeEngine):
    def __init__(
        self, 
        *args, 
        worker_class: str = "distributed.cli.Nanny",
        worker_options: dict = {}, 
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.worker_class = worker_class
        self.worker_options = worker_options

        internal_scheduler = f"ws://{self.cluster.scheduler_internal_ip}:80"

        self.command = [
            "python",
            "-m",
            "distributed.cli.dask_spec",
            internal_scheduler,
            "--spec",
            json.dumps(
                {
                    "cls": self.worker_class,
                    "opts": {
                        **worker_options,
                        "name": self.name,
                    },
                }
            ),
        ]

class IBMCodeEngineCluster(VMCluster):
    def __init__(
        self,
        image: str = None,
        region: str = None,
        project_id: str = None,
        debug: bool = False,
        security: bool = True,
        **kwargs,
    ):
        self.config = ClusterConfig(dask.config.get("cloudprovider.ibm", {}))
        self.scheduler_class = IBMCodeEngineScheduler
        self.worker_class = IBMCodeEngineWorker
        
        self.image = image or self.config.get("image")
        self.region = region or self.config.get("region")
        self.project_id = project_id or self.config.get("project_id")
        api_key = self.config.get("api_key")

        self.debug = debug
        
        self.options = {
            "cluster": self,
            "config": self.config,
            "image": self.image,
            "region": self.region,
            "project_id": self.project_id,
            "api_key": api_key,
        }
        self.scheduler_options = {**self.options}
        self.worker_options = {**self.options}

        # https://letsencrypt.org/certificates/ --> ISRG Root X1
        sec = Security(require_encryption=False, tls_ca_file="-----BEGIN CERTIFICATE-----\nMIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw\nTzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh\ncmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4\nWhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu\nZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY\nMTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc\nh77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+\n0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U\nA5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW\nT8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH\nB5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC\nB5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv\nKBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn\nOlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn\njh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw\nqHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI\nrU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV\nHRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq\nhkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL\nubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ\n3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK\nNFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5\nORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur\nTkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC\njNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc\noyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq\n4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA\nmRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d\nemyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=\n-----END CERTIFICATE-----")
        super().__init__(security=sec, debug=debug, **kwargs)
