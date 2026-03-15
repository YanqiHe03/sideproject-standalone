"""
OSC client wrapper.
"""

from pythonosc import udp_client
from config import OSC_TARGET_IP, OSC_TARGET_PORT


def create_osc_client():
    """Create and return an OSC UDP client."""
    print(f"OSC Client targeting: {OSC_TARGET_IP}:{OSC_TARGET_PORT}")
    return udp_client.SimpleUDPClient(OSC_TARGET_IP, OSC_TARGET_PORT)
