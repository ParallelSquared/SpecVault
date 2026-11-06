"""The name of the computer at a network address, for the history.

Two ways of asking, in turn:

1. **NetBIOS**, by asking the computer itself. Windows answers a "node
   status" query on UDP port 137 with its own computer name -- the same
   question `nbtstat -A` and `nmblookup -A` ask -- and so do the lab's Macs
   (MAC-30528C, MACBOOK-PRO-2): of the 18 machines a lab PC could see on
   2026-11-06, every one with a name gave it this way. Asked directly from
   Python, so the server needs nothing installed for it, and first because
   it answers in milliseconds.
2. **DNS**, a reverse lookup, for anything that will not say. From the
   Linux server the lab's DNS has no names for the PCs at all -- which is why
   this file exists -- but it costs nothing to ask.

A machine whose firewall drops the question (a laptop on a network Windows
calls Public, say) gives no name either way, and is recorded by address.
"""
import ipaddress
import os
import socket
import struct
from typing import Optional

NETBIOS_PORT = 137
NETBIOS_TIMEOUT = 1.0  # seconds; a PC on the same network answers in a few ms

# A node status request for the wildcard name "*", in NetBIOS's own encoding:
# each byte of the 16-byte name as two letters, 'A' plus each half-byte.
_WILDCARD = b"*" + b"\0" * 15
_ENCODED = bytes(c for byte in _WILDCARD for c in (65 + (byte >> 4), 65 + (byte & 0xF)))
_NBSTAT, _IN = 0x21, 0x01


def name_of(address: str) -> Optional[str]:
    """The computer's name, or None when nobody will say."""
    return netbios_name(address) or _from_dns(address)


def _from_dns(address: str) -> Optional[str]:
    try:
        return socket.gethostbyaddr(address)[0]
    except OSError:
        return None


def _request(transaction: int) -> bytes:
    header = struct.pack(">HHHHHH", transaction, 0, 1, 0, 0, 0)
    question = bytes([32]) + _ENCODED + b"\0" + struct.pack(">HH", _NBSTAT, _IN)
    return header + question


def netbios_name(address: str, timeout: float = NETBIOS_TIMEOUT) -> Optional[str]:
    """The name Windows calls itself, asked of the computer at *address*."""
    try:
        ipaddress.IPv4Address(address)
    except ValueError:
        return None  # NetBIOS is IPv4 only, and asks addresses, not names
    transaction = int.from_bytes(os.urandom(2), "big")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(_request(transaction), (address, NETBIOS_PORT))
            while True:
                reply, sender = sock.recvfrom(4096)
                if sender[0] == address and reply[:2] == transaction.to_bytes(2, "big"):
                    return parse_status(reply)
    except (OSError, ValueError):
        return None


def parse_status(reply: bytes) -> Optional[str]:
    """The computer's own name from a node status reply: the first unique
    name of type 0x00 (the workstation), as against group names such as its
    workgroup, which share the type."""
    try:
        at = 12
        while reply[at]:  # the name asked about, label by label
            at += reply[at] + 1
        at += 1 + 10  # its terminator; then type, class, time to live, length
        count = reply[at]
        at += 1
        for _ in range(count):
            raw, suffix, flags = reply[at:at + 15], reply[at + 15], struct.unpack(">H", reply[at + 16:at + 18])[0]
            at += 18
            is_group = flags & 0x8000
            if suffix == 0x00 and not is_group:
                return raw.decode("ascii", errors="replace").strip() or None
    except (IndexError, struct.error):
        pass
    return None
