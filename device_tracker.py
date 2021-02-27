"""Tracking for BT and BT LE devices."""
import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.device_tracker import PLATFORM_SCHEMA, see
from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.components.device_tracker.const import (
    CONF_TRACK_NEW,
    CONF_SCAN_INTERVAL,
    SCAN_INTERVAL,
    DEFAULT_TRACK_NEW,
    SOURCE_TYPE_BLUETOOTH,
    DOMAIN,
)
from homeassistant.const import CONF_DEVICE, EVENT_HOMEASSISTANT_STOP
import homeassistant.util.dt as dt_util

from pydbus import SystemBus
from gi.repository import GLib
from xml.etree import ElementTree
from threading import Thread
import asyncio

_LOGGER = logging.getLogger(__name__)

BTD_PREFIX = "BTD_"
DATA_BT_DBUS_TRACKER = 'bluetooth_dbus_tracker'


async def async_setup_scanner(hass, config, async_see, discovery_info):
    """Setup device tracker platform."""
    scanner = BluetoothDBusScanner(hass, config)
    hass.data[DATA_BT_DBUS_TRACKER] = {
        'scanner': scanner,
        'devices': []
    }
    scanner.start()
    return True


class BluetoothDBusScanner():
    """Bluetooth DBus Scanner."""

    def __init__(self, hass, config):
        """Initialize the tracker."""
        self.hass = hass
        self._bus = SystemBus()
        self._devname = config.get(CONF_DEVICE, 'hci0') 
        self._dev = self._bus.get("org.bluez", self._devname)
        self._glib_loop = GLib.MainLoop()
        self._subscription = self._bus.subscribe(
            object="/",
            iface="org.freedesktop.DBus.ObjectManager",
            signal="InterfacesAdded",
            signal_fired=self.device_detected)

    def start(self):
        """Collect and report detected devices."""
        _LOGGER.debug("Starting bluetooth_dbus scan task.")
        self.clear_all_devices()
        self._dev.SetDiscoveryFilter({})
        self._dev.StartDiscovery()
        self._scanner = ScannerThread(self._glib_loop)
        
        async def run_scan():
            """Start scanning thread and listen for HA stop."""
            async def stop(event):
                """Handle HA stop."""
                self._scanner.stop()
                self._scanner.join()

            self.hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, stop)
            self._scanner.start()
        self.hass.loop.create_task(run_scan())

    def device_detected(self, sender, object, iface, signal, params):
        """Handle detected device."""
        device = params[1]['org.bluez.Device1']
        mac = device['Address']
        rssi = device['RSSI']
        see(self.hass, mac, host_name=device['Alias'], 
            attributes={'friendly_name': device['Alias'],
                        'source_type': SOURCE_TYPE_BLUETOOTH,
                        'rssi': rssi})
        self._dev.RemoveDevice(params[0])

    def clear_all_devices(self):
        """Clear the list of current devices on the adapter."""
        for child in ElementTree.fromstring(self._dev.Introspect()):
            if child.tag == 'node':
                self._dev.RemoveDevice(
                    "/org/bluez/hci0/{}".format(child.attrib["name"]))


class ScannerThread(Thread):
    """Bluetooth DBus device scanner thread."""

    def __init__(self, glib_loop):
        """Initialize scanner values."""
        super().__init__()
        self._glib_loop = glib_loop

    def run(self):
        """Start the scanner."""
        self._glib_loop.run()

    def stop(self):
        self._glib_loop.quit()

