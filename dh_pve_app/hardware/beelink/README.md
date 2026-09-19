# Beelink / AZW IT8613E host profile

This profile prepares a supported Beelink/AZW mini PC running Proxmox VE so the
Linux hwmon stack exposes the IT8613E fan tachometer reliably after every boot.

It is intentionally separate from the generic `dh_pve_app/install.sh`. A custom
kernel driver must never be installed automatically on unrelated Proxmox hosts.

## What it installs

The installer uses the normal Debian/Proxmox kernel-module path:

1. validates root, Proxmox VE and Beelink/AZW DMI identity;
2. installs `dkms`, build tools, `proxmox-default-headers` and headers for the
   running kernel through APT;
3. downloads only the required upstream `frankcrawford/it87` source files from
   the pinned commit
   `bc06d3488439e5fcd725c1bdcfcac994d6d95cac`;
4. verifies every downloaded file against its pinned Git blob SHA;
5. installs the source under `/usr/src/it87-v2.0-4-gbc06d34.20260913`;
6. registers it through DKMS and builds/installs it for the running PVE kernel and every newer installed PVE kernel that has matching headers, including an already-installed next boot kernel;
7. creates `/etc/modules-load.d/digitalhouses-beelink-it87.conf`;
8. loads the module with normal `modprobe it87`;
9. verifies the IT8613E hwmon device and `fan2_input`;
10. when `dh_pve_app` is installed, verifies that its raw collector sees
    `it8613_it87_2608_fan2`.

The upstream `dkms.conf` has `AUTOINSTALL="yes"`, so future Proxmox kernel
installs can rebuild this pinned driver when matching headers are present.

## Safety model

The profile does **not** replace or delete the stock Proxmox
`it87` kernel module. DKMS installs the custom build in the normal higher
priority DKMS module location, and `depmod`/modprobe select it through the
system module database.

The profile does not use `force_id`, `fix_pwm_polarity`,
`ignore_resource_conflict`, direct `insmod`, direct `rmmod`, or any PWM
control. It only enables hwmon telemetry.

A machine whose DMI identity does not contain `AZW` or `Beelink` is rejected.
After driver activation the installer additionally requires a real `it8613`
hwmon device and readable `fan2_input`.

## Install or repair

From a reviewed checkout/ref:

```bash
sudo bash dh_pve_app/hardware/beelink/install.sh
```

The operation is idempotent. Re-running it repairs missing packages/source or
autoload state, verifies the running kernel and every newer installed PVE kernel with matching headers, and
does not create a second DKMS version.

If a different `it87` module is already loaded, the installer does not unload
it underneath a running host. It finishes the persistent setup and reports
`REBOOT_REQUIRED=yes`. One normal reboot then activates the pinned DKMS build.

## Read-only check

```bash
sudo bash dh_pve_app/hardware/beelink/install.sh --check
```

A healthy host ends with:

```text
CHECK=PASS
```

The check validates DMI, current-kernel DKMS installation, module resolution,
autoload, loaded driver version, IT8613E hwmon and the App collector when the App
is present.

## Uninstall / rollback

```bash
sudo bash dh_pve_app/hardware/beelink/uninstall.sh
```

The uninstaller removes only the DigitalHouses autoload file, the pinned DKMS
version and its `/usr/src` source directory. It does not touch the stock
Proxmox module.

If the custom module is currently loaded, it is deliberately left in memory
until reboot; a reboot returns the host to the normal stock module state.

Older installed PVE kernels are intentionally ignored: they are not future boot targets and driver incompatibility there must not block preparing the current or next kernel.
