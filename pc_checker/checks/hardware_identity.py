"""Manufacturer / model identification for major PC components (WMI/CIM + sample PnP)."""

from __future__ import annotations

import sys
from typing import Any

from pc_checker.powershell import run_json

# Script output is a single PSCustomObject; run_json wraps with outer ConvertTo-Json.
_SCRIPT = r"""
function Decode-CharArray($a) {
  if ($null -eq $a) { return $null }
  if ($a -is [string]) { return $a }
  try {
    $chars = @($a | Where-Object { $_ -and $_ -ne 0 })
    if (-not $chars.Count) { return $null }
    return -join ($chars | ForEach-Object { [char][int]$_ })
  } catch { return $null }
}

$mon = @()
try {
  Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorID -ErrorAction SilentlyContinue | ForEach-Object {
    $mon += [PSCustomObject]@{
      Manufacturer = (Decode-CharArray $_.ManufacturerName)
      Product        = (Decode-CharArray $_.UserFriendlyName)
      Serial         = (Decode-CharArray $_.SerialNumberID)
    }
  }
} catch { }

$usb = @()
try {
  Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Class -match '^(USB|HIDClass|Keyboard|Mouse|Bluetooth|Camera|Image|USBDevice|AudioEndpoint)$' -and $_.FriendlyName
    } |
    Select-Object -First 55 FriendlyName, Class, @{n='Mfg';e={ $_.Manufacturer } } |
    ForEach-Object { $usb += $_ }
} catch { }

[PSCustomObject]@{
  ComputerSystem = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue |
    Select-Object Manufacturer, Model, SystemSKUNumber, TotalPhysicalMemory
  BaseBoard = Get-CimInstance Win32_BaseBoard -ErrorAction SilentlyContinue |
    Select-Object Manufacturer, Product, Version, SerialNumber
  BIOS = Get-CimInstance Win32_BIOS -ErrorAction SilentlyContinue |
    Select-Object Manufacturer, SMBIOSBIOSVersion, ReleaseDate, SerialNumber
  Chassis = Get-CimInstance Win32_SystemEnclosure -ErrorAction SilentlyContinue |
    Select-Object Manufacturer, Model, ChassisTypes
  Cpu = Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue |
    Select-Object -First 1 Name, Manufacturer, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed
  Gpu = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
    Select-Object Name, AdapterRAM, DriverVersion, VideoProcessor, PNPDeviceID)
  MemoryModules = @(Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue |
    Select-Object Manufacturer, PartNumber, Capacity, Speed, FormFactor, SMBIOSMemoryType)
  DiskDrives = @(Get-CimInstance Win32_DiskDrive -ErrorAction SilentlyContinue |
    Select-Object Model, Manufacturer, InterfaceType, MediaType, Size, SerialNumber)
  SoundDevices = @(Get-CimInstance Win32_SoundDevice -ErrorAction SilentlyContinue |
    Select-Object Name, Manufacturer, Status)
  NetworkAdapters = @(Get-CimInstance Win32_NetworkAdapter -ErrorAction SilentlyContinue |
    Where-Object { $_.PhysicalAdapter -eq $true } |
    Select-Object Name, Manufacturer, ProductName, MACAddress, NetEnabled, NetConnectionStatus)
  Monitors = @($mon)
  UsbAndPeripheralSample = @($usb)
  note = 'OEM model from Win32_ComputerSystem; monitors from root\\wmi WmiMonitorID; USB/HID sample is partial. Some fields blank on custom builds or without drivers.'
}
"""


def collect_hardware_identity() -> dict[str, Any]:
    if sys.platform != "win32":
        return {"platform": "non-windows", "skipped": True}
    data = run_json(_SCRIPT.strip(), timeout=95)
    if not isinstance(data, dict):
        return {"error": "no data or query failed"}
    return data
