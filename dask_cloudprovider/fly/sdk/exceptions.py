# @see https://github.com/bwhli/fly-python-sdk/blob/main/fly_python_sdk/exceptions.py


class AppInterfaceError(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


class MissingApiHostnameError(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


class MissingApiTokenError(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


class MissingMachineIdsError(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


class MachineInterfaceError(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message
