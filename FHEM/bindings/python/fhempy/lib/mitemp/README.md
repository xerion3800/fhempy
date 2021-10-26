
# Xiaomi Mi Bluetooth Low Energy Temperature / Humidity Sensor
This module is used to get data from the Xiaomi BLE temperature / humidity sensor.

## Installation
Add the following settings to `/etc/dbus-1/system.d/bluetooth.conf`
```
  <policy user="fhem">
    <allow own="org.bluez"/>
    <allow send_destination="org.bluez"/>
    <allow send_interface="org.bluez.GattCharacteristic1"/>
    <allow send_interface="org.bluez.GattDescriptor1"/>
    <allow send_interface="org.freedesktop.DBus.ObjectManager"/>
    <allow send_interface="org.freedesktop.DBus.Properties"/>
  </policy>
```
Set the user to the one which runs fhempy. On FHEM installations it's fhem, on remote peers it's normally pi.
Restart dbus afterwards: `sudo systemctl restart dbus`

## Usage
```
define mi_temphum fhempy mitemp <MAC>
```