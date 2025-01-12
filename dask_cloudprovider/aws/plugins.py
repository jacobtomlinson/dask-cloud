import logging
import os
from pathlib import Path

from distributed import WorkerPlugin

logger = logging.getLogger(__name__)

class UploadAWSCredentials(WorkerPlugin):
    # """Automatically upload a GCP key to the worker."""

    name = "upload_aws_credentials"

    def __init__(self):
        """
        Initialize the plugin by reading in the data from the given file.
        """
        config_path = os.getenv("AWS_CONFIG_FILE", Path.home() / Path(".aws/config"))
        credentials_path = os.getenv(
            "AWS_SHARED_CREDENTIALS_FILE", Path.home() / Path(".aws/credentials")
        )
        config_path, credentials_path = Path(config_path), Path(credentials_path)

        if not config_path.exists():
            raise ValueError(
                f"Config file {config_path} does not exist. If you store AWS config "
                "in a different location, please set AWS_CONFIG_FILE environment variable."
            )

        if not credentials_path.exists():
            raise ValueError(
                f"Credentials file {credentials_path} does not exist. If you store AWS credentials "
                "in a different location, please set AWS_SHARED_CREDENTIALS_FILE environment variable."
            )

        self.config_filename = config_path.name
        self.credentials_filename = credentials_path.name

        with open(config_path, "rb") as f:
            self.config = f.read()
        with open(credentials_path, "rb") as f:
            self.credentials = f.read()

    async def setup(self, worker):
        await worker.upload_file(
            filename=self.config_filename, data=self.config, load=False
        )
        worker_config_path = Path(worker.local_directory) / self.config_filename
        os.environ["AWS_CONFIG_FILE"] = str(worker_config_path)

        await worker.upload_file(
            filename=self.credentials_filename, data=self.credentials, load=False
        )
        worker_credentials_path = (
            Path(worker.local_directory) / self.credentials_filename
        )
        os.environ["AWS_SHARED_CREDENTIALS_FILE"] = str(worker_credentials_path)