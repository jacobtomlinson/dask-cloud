import logging
import os
from pathlib import Path

from distributed import WorkerPlugin
from google.auth._cloud_sdk import get_application_default_credentials_path

logger = logging.getLogger(__name__)

class UploadGCPKey(WorkerPlugin):
    """Automatically upload a GCP key to the worker."""

    name = "upload_gcp_key"

    def __init__(self):
        """
        Initialize the plugin by reading in the data from the given file.
        """
        key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if key_path is None:
            key_path = Path(get_application_default_credentials_path())
            if not key_path.exists():
                raise ValueError("GOOGLE_APPLICATION_CREDENTIALS is not set or `gcloud auth application-default login` wasn't run.")

        key_path = Path(key_path)
        self.filename = key_path.name

        logger.info("Uploading GCP key from %s.", str(key_path))

        with open(key_path, "rb") as f:
            self.data = f.read()

    async def setup(self, worker):
        await worker.upload_file(filename=self.filename, data=self.data, load=False)
        worker_key_path = Path(worker.local_directory) / self.filename
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(worker_key_path)