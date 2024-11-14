import socket
import asyncio


def is_socket_open(ip, port):
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        connection.connect((ip, int(port)))
        connection.shutdown(2)
        return True
    except Exception:
        return False


def is_ipv6_socket_open(ip, port):
    connection = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        connection.connect((ip, int(port)))
        connection.shutdown(2)
        return True
    except Exception:
        return False


async def async_socket_open(address, port):
    loop = asyncio.get_event_loop()
    try:
        res = await loop.sock_connect(address, port)
        res.close()
        return True
    except Exception:
        return False
