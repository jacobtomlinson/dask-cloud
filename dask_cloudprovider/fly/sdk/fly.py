# @see https://github.com/bwhli/fly-python-sdk/blob/main/fly_python_sdk/fly.py

import os
from typing import Union

import httpx
from pydantic import BaseModel

from .exceptions import (
    AppInterfaceError,
    MachineInterfaceError,
    MissingMachineIdsError,
)
from .models.apps import (
    FlyAppCreateRequest,
    FlyAppCreateResponse,
    FlyAppDetailsResponse,
    FlyAppDeleteResponse,
)
from .models.machines import FlyMachineConfig, FlyMachineDetails


class Fly:
    """
    A class for interacting with the Fly.io platform.
    """

    def __init__(self, api_token: str) -> None:
        self.api_token = api_token
        self.api_version = 1

    ########
    # Apps #
    ########

    async def create_app(
        self,
        app_name: str,
        org_slug: str = "personal",
    ) -> FlyAppCreateResponse:
        """Creates a new app on Fly.io.

        Args:
            app_name: The name of the new Fly.io app.
            org_slug: The slug of the organization to create the app within.
                      If None, the personal organization will be used.
        """
        path = "apps"
        app_details = FlyAppCreateRequest(app_name=app_name, org_slug=org_slug)
        r = await self._make_api_post_request(path, app_details.dict())

        # Raise an exception if HTTP status code is not 201.
        if r.status_code != 201:
            error_msg = r.json().get("error", {}).get("message", "Unknown error!")
            raise AppInterfaceError(
                message=f"Unable to create {app_name} in {org_slug}! Error: {error_msg}"
            )
        return FlyAppCreateResponse(app_name=app_name, org_slug=org_slug)

    async def get_app(
        self,
        app_name: str,
    ) -> FlyAppDetailsResponse:
        """Returns information about a Fly.io application.

        Args:
            app_name: The name of the new Fly.io app.
        """
        path = f"apps/{app_name}"
        r = await self._make_api_get_request(path)

        # Raise an exception if HTTP status code is not 200.
        if r.status_code != 200:
            raise AppInterfaceError(message=f"Unable to get {app_name}!")

        return FlyAppDetailsResponse(**r.json())

    async def delete_app(
        self,
        app_name: str,
        force: bool = False,
    ) -> None:
        """Deletes a Fly.io application.

        Args:
            app_name: The name of the new Fly.io app.
            force: If True, the app will be deleted even if it has active machines.
        """
        path = f"apps/{app_name}?force={str(force).lower()}"
        r = await self._make_api_delete_request(path)

        # Raise an exception if HTTP status code is not 200.
        if r.status_code != 202:
            raise AppInterfaceError(
                message=f"Unable to delete {app_name}! status_code={r.status_code}"
            )

        return FlyAppDeleteResponse(
            status=r.status_code,
            app_name=app_name,
        )

    ############
    # Machines #
    ############

    async def list_machines(
        self,
        app_name: str,
        ids_only: bool = False,
    ) -> Union[list[FlyMachineDetails], list[str]]:
        """Returns a list of machines that belong to a Fly.io application.

        Args:
            ids_only: If True, only machine IDs will be returned. Defaults to False.
        """
        path = f"apps/{app_name}/machines"
        r = await self._make_api_get_request(path)

        # Raise an exception if HTTP status code is not 200.
        if r.status_code != 200:
            raise AppInterfaceError(message=f"Unable to get machines in {app_name}!")

        # Create a FlyMachineDetails object for each machine.
        machines = [FlyMachineDetails(**machine) for machine in r.json()]

        # Filter and return a list of ids if ids_only is True.
        if ids_only is True:
            return [machine.id for machine in machines]

        return machines

    async def create_machine(
        self,
        app_name: str,
        config: FlyMachineConfig,
        name: str = None,
        region: str = None,
    ):
        """Creates a Fly.io machine.

        Args:
            app_name: The name of the new Fly.io app.
            config: A FlyMachineConfig object containing creation details.
            name: The name of the machine.
            region: The deployment region for the machine.
        """
        path = f"apps/{app_name}/machines"

        # Create Pydantic model for machine creation requests.
        class _FlyMachineCreateRequest(BaseModel):
            name: Union[str, None] = None
            region: Union[str, None] = None
            config: FlyMachineConfig

        # Create FlyMachineCreateRequest object
        machine_create_request = _FlyMachineCreateRequest(
            name=name,
            region=region,
            config=config,
        )

        r = await self._make_api_post_request(
            path,
            payload=machine_create_request.dict(exclude_defaults=True),
        )

        # Raise an exception if HTTP status code is not 200.
        if r.status_code != 200:
            raise MachineInterfaceError(
                message=f"{r.status_code}: Unable to create machine!"
            )

        return FlyMachineDetails(**r.json())

    async def delete_machine(
        self,
        app_name: str,
        machine_id: str,
        force: bool = False,
    ) -> None:
        """Deletes a Fly.io machine.

        Args:
            app_name: The name of the new Fly.io app.
            machine_id: The id string for a Fly.io machine.
            force: If True, the machine will be deleted even if it is running.
        """
        path = f"apps/{app_name}/machines/{machine_id}?force={str(force).lower()}"
        r = await self._make_api_delete_request(path)

        # Raise an exception if HTTP status code is not 200.
        if r.status_code != 200:
            raise MachineInterfaceError(
                message=f"Unable to delete {machine_id} in {app_name}!"
            )

        return

    async def delete_machines(
        self,
        app_name: str,
        machine_ids: list[str] = [],
        delete_all: bool = False,
        force: bool = False,
    ) -> None:
        """Deletes multiple Fly.io machines.

        Args:
            app_name: The name of the new Fly.io app.
            machine_ids: An array of machine IDs to delete.
            delete_all: Delete all machines in the app if True.
            force: Delete even if running
        """
        # If delete_all is True, override provided machine_ids.
        if delete_all is True:
            machine_ids = self.list_machines(app_name, ids_only=True)

        # Raise an exception if there are no machine IDs to delete.
        if len(machine_ids) == 0:
            raise MissingMachineIdsError(
                "Please provide at least one machine ID to delete."
            )

        # Stop machines.
        for machine_id in machine_ids:
            self.stop_machine(app_name, machine_id)

        # Delete machines.
        for machine_id in machine_ids:
            self.delete_machine(app_name, machine_id, force=force)

        return

    async def get_machine(
        self,
        app_name: str,
        machine_id: str,
    ) -> FlyMachineDetails:
        """Returns information about a Fly.io machine.

        Args:
            app_name: The name of the new Fly.io app.
            machine_id: The id string for a Fly.io machine.
        """
        path = f"apps/{app_name}/machines/{machine_id}"
        r = await self._make_api_get_request(path)

        # Raise an exception if HTTP status code is not 200.
        if r.status_code != 200:
            raise MachineInterfaceError(
                message=f"Unable to delete {machine_id} in {app_name}!"
            )

        return FlyMachineDetails(**r.json())

    async def start_machine(
        self,
        app_name: str,
        machine_id: str,
    ) -> None:
        """Starts a Fly.io machine.

        Args:
            app_name: The name of the new Fly.io app.
            machine_id: The id string for a Fly.io machine.
        """
        path = f"apps/{app_name}/machines/{machine_id}/start"
        r = await self._make_api_post_request(path)

        # Raise an exception if HTTP status code is not 200.
        if r.status_code != 200:
            raise MachineInterfaceError(
                message=f"Unable to start {machine_id} in {app_name}!"
            )

        return

    async def stop_machine(
        self,
        app_name: str,
        machine_id: str,
    ) -> None:
        """Stop a Fly.io machine.

        Args:
            app_name: The name of the new Fly.io app.
            machine_id: The id string for a Fly.io machine.
        """
        path = f"apps/{app_name}/machines/{machine_id}/stop"
        r = await self._make_api_post_request(path)

        # Raise an exception if HTTP status code is not 200.
        if r.status_code != 200:
            raise MachineInterfaceError(
                message=f"Unable to stop {machine_id} in {app_name}!"
            )

        return

    #############
    # Utilities #
    #############

    async def _make_api_delete_request(
        self,
        path: str,
    ) -> httpx.Response:
        """An internal function for making DELETE requests to the Fly.io API."""
        api_hostname = self._get_api_hostname()
        url = f"{api_hostname}/v{self.api_version}/{path}"
        async with httpx.AsyncClient(verify=False, timeout=None) as client:
            r = await client.delete(url, headers=self._generate_headers())
            r.raise_for_status()
        return r

    async def _make_api_get_request(
        self,
        path: str,
    ) -> httpx.Response:
        """An internal function for making GET requests to the Fly.io API."""
        api_hostname = self._get_api_hostname()
        url = f"{api_hostname}/v{self.api_version}/{path}"
        async with httpx.AsyncClient(verify=False, timeout=None) as client:
            r = await client.get(url, headers=self._generate_headers())
            r.raise_for_status()
        return r

    async def _make_api_post_request(
        self,
        path: str,
        payload: dict = {},
    ) -> httpx.Response:
        """An internal function for making POST requests to the Fly.io API."""
        api_hostname = self._get_api_hostname()
        url = f"{api_hostname}/v{self.api_version}/{path}"
        headers = self._generate_headers()
        async with httpx.AsyncClient(verify=False, timeout=None) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
        return r

    def _generate_headers(self) -> dict:
        """Returns a dictionary containing headers for requests to the Fly.io API."""
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        return headers

    def _get_api_hostname(self) -> str:
        """Returns the hostname that will be used to connect to the Fly.io API.

        Returns:
            The hostname that will be used to connect to the Fly.io API.
            If the FLY_API_HOSTNAME environment variable is not set,
            the hostname returned will default to https://api.machines.dev.
        """
        api_hostname = os.getenv("FLY_API_HOSTNAME", "https://api.machines.dev")
        return api_hostname
