"""
USB audio disable/enable for SCUF Envision Pro V2.

Controls the snd-usb-audio kernel driver binding for SCUF audio interfaces.
Unbinding removes the audio device entirely from the system (PipeWire won't
see it). Rebinding restores it.

Requires root (writes to /sys/bus/usb/drivers/snd-usb-audio/{unbind,bind}).
"""

import glob
import logging
import os
from pathlib import Path

from .constants import SCUF_VENDOR_ID, SCUF_PRODUCT_ID_WIRED, SCUF_PRODUCT_ID_RECEIVER

log = logging.getLogger(__name__)

SND_USB_AUDIO_DRIVER = "/sys/bus/usb/drivers/snd-usb-audio"


def _read_sysfs(path):
    """Read a sysfs attribute, return empty string on failure."""
    try:
        return Path(path).read_text().strip()
    except (OSError, IOError):
        return ""


def _match_scuf_vid_pid(sysfs_dir):
    """Walk up from sysfs_dir to find idVendor/idProduct and check for SCUF match."""
    target_vid = f"{SCUF_VENDOR_ID:04x}"
    target_pids = {f"{SCUF_PRODUCT_ID_WIRED:04x}", f"{SCUF_PRODUCT_ID_RECEIVER:04x}"}

    check = sysfs_dir
    for _ in range(10):
        check = os.path.dirname(check)
        if not check or check == "/":
            break
        vid_path = os.path.join(check, "idVendor")
        pid_path = os.path.join(check, "idProduct")
        if os.path.isfile(vid_path) and os.path.isfile(pid_path):
            vid = _read_sysfs(vid_path)
            pid = _read_sysfs(pid_path)
            return vid == target_vid and pid in target_pids
    return False


def _find_scuf_audio_interfaces(bound_only=True):
    """
    Find USB interface identifiers for SCUF audio devices.

    Args:
        bound_only: If True, only return interfaces currently bound to
                    snd-usb-audio. If False, scan all USB interfaces for
                    SCUF audio-class devices (bound or not).

    Returns:
        List of interface identifiers (e.g. "3-2:1.0") suitable for
        writing to unbind/bind.
    """
    results = []

    if bound_only:
        if not os.path.isdir(SND_USB_AUDIO_DRIVER):
            log.debug("snd-usb-audio driver directory not found")
            return []

        for entry in os.listdir(SND_USB_AUDIO_DRIVER):
            entry_path = os.path.join(SND_USB_AUDIO_DRIVER, entry)
            if not os.path.islink(entry_path):
                continue
            real = os.path.realpath(entry_path)
            if _match_scuf_vid_pid(real):
                results.append(entry)
                log.debug("Found bound SCUF audio interface: %s", entry)
    else:
        # Scan all USB interfaces for bInterfaceClass=01 (USB Audio)
        for intf_dir in glob.glob("/sys/bus/usb/devices/*:*"):
            intf_class = _read_sysfs(os.path.join(intf_dir, "bInterfaceClass"))
            if intf_class != "01":
                continue
            parent = os.path.dirname(intf_dir)
            target_vid = f"{SCUF_VENDOR_ID:04x}"
            target_pids = {f"{SCUF_PRODUCT_ID_WIRED:04x}", f"{SCUF_PRODUCT_ID_RECEIVER:04x}"}
            vid = _read_sysfs(os.path.join(parent, "idVendor"))
            pid = _read_sysfs(os.path.join(parent, "idProduct"))
            if vid == target_vid and pid in target_pids:
                intf_id = os.path.basename(intf_dir)
                results.append(intf_id)
                log.debug("Found SCUF USB audio interface: %s", intf_id)

    return results


def unbind_scuf_audio():
    """
    Unbind all SCUF audio interfaces from snd-usb-audio.

    Returns the number of interfaces unbound.
    """
    interfaces = _find_scuf_audio_interfaces(bound_only=True)
    if not interfaces:
        log.info("No SCUF audio interfaces currently bound to snd-usb-audio")
        return 0

    unbind_path = os.path.join(SND_USB_AUDIO_DRIVER, "unbind")
    count = 0
    for intf_id in interfaces:
        try:
            with open(unbind_path, "w") as f:
                f.write(intf_id)
            log.info("Unbound SCUF audio interface: %s", intf_id)
            count += 1
        except OSError as e:
            log.error("Failed to unbind %s: %s", intf_id, e)

    return count


def rebind_scuf_audio():
    """
    Rebind SCUF audio interfaces to snd-usb-audio.

    Finds unbound SCUF USB audio-class interfaces and writes them to the
    driver's bind file.

    Returns the number of interfaces rebound.
    """
    all_interfaces = _find_scuf_audio_interfaces(bound_only=False)
    bound_interfaces = set(_find_scuf_audio_interfaces(bound_only=True))
    unbound = [i for i in all_interfaces if i not in bound_interfaces]

    if not unbound:
        log.info("All SCUF audio interfaces already bound (or device not connected)")
        return 0

    bind_path = os.path.join(SND_USB_AUDIO_DRIVER, "bind")
    count = 0
    for intf_id in unbound:
        try:
            with open(bind_path, "w") as f:
                f.write(intf_id)
            log.info("Rebound SCUF audio interface: %s", intf_id)
            count += 1
        except OSError as e:
            log.error("Failed to rebind %s: %s", intf_id, e)

    return count


def apply_audio_config():
    """
    Read config and apply the audio disabled/enabled state.

    Called at driver startup and on wireless reconnect.
    """
    from .config import is_audio_disabled

    if is_audio_disabled():
        n = unbind_scuf_audio()
        if n > 0:
            log.info("Audio disabled: unbound %d SCUF audio interface(s)", n)
        else:
            log.info("Audio disabled in config (no interfaces to unbind)")
    else:
        n = rebind_scuf_audio()
        if n > 0:
            log.info("Audio enabled: rebound %d SCUF audio interface(s)", n)
