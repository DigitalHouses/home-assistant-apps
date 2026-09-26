# Beelink / AZW IT8613E host profile

This profile prepares a supported Beelink/AZW mini PC running Proxmox VE so the
Linux hwmon stack exposes the IT8613E fan tachometer reliably after every boot.

It is intentionally separate from the generic `digitalhouses_pve_agent/install.sh`. A custom
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
10. when `digitalhouses_pve_agent` is installed, verifies that its raw collector sees
    `it8613_it87_2608_fan2`.

The upstream `dkms.conf` has `AUTOINSTALL="yes"`, so future Proxmox kernel
installs can rebuild this pinned driver when matching headers are present.

## Safety model

The profile does **not** replace or delete the stock Proxmox
`it87` kernel module. DKMS installs the custom build in the normal higher
priority DKMS module location, and `depmod`/modprobe select it through the
system module database.

The host-profile installer does not use `force_id`, `fix_pwm_polarity`,
`ignore_resource_conflict`, direct `insmod`, direct `rmmod`, or PWM
control. It only prepares the pinned driver and hwmon telemetry.

A newer `digitalhouses_pve_agent` release may separately use the explicitly supported
Beelink IT8613 `fan2/pwm2` adapter for guarded fan calibration. That runtime
path is hardware-profile-aware, persists the original control state before the
first write, drives the fan only to maximum, restores/verifies the original
state, and never writes PWM on an unmatched hwmon device.

A machine whose DMI identity does not contain `AZW` or `Beelink` is rejected.
After driver activation the installer additionally requires a real `it8613`
hwmon device and readable `fan2_input`.

## Standalone use

This hardware profile is independent from the generic App installer. Do not
assume that an older already-installed `digitalhouses_pve_agent` release contains
`hardware/beelink/` under `/opt/digitalhouses/digitalhouses_pve_agent`.

Production use follows the same immutable-delivery rule as the App: run the
hardware profile from a canonical `digitalhouses_pve_agent-v<version>` release
tag. Branch, `main` and arbitrary-SHA execution are development/recovery paths,
not normal production installation.

### Install or repair

```bash
TAG=digitalhouses_pve_agent-v0.5.32
bash <(curl -fsSL "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/$TAG/digitalhouses_pve_agent/hardware/beelink/install.sh")
```

### Read-only check

```bash
TAG=digitalhouses_pve_agent-v0.5.32
bash <(curl -fsSL "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/$TAG/digitalhouses_pve_agent/hardware/beelink/install.sh") --check
```

A healthy host ends with:

```text
CHECK=PASS
```

The check validates DMI, current-kernel DKMS installation, module resolution,
autoload, loaded driver version, IT8613E hwmon and the App collector when the App
is present.

### Uninstall / rollback

```bash
TAG=digitalhouses_pve_agent-v0.5.32
bash <(curl -fsSL "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/$TAG/digitalhouses_pve_agent/hardware/beelink/uninstall.sh")
```

### Development / recovery only

For an explicitly reviewed branch or full commit SHA:

```bash
REF=<branch-or-full-sha>
bash <(curl -fsSL "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/$REF/digitalhouses_pve_agent/hardware/beelink/install.sh")
```

A reviewed local checkout is likewise a development/recovery path:

```bash
sudo bash digitalhouses_pve_agent/hardware/beelink/install.sh
```

The operation is idempotent. Re-running it repairs missing packages/source or
autoload state, verifies the running kernel and every newer installed PVE kernel
with matching headers, and does not create a second DKMS version.

If a different `it87` module is already loaded, the installer does not unload
it underneath a running host. It finishes the persistent setup and reports
`REBOOT_REQUIRED=yes`. One normal reboot then activates the pinned DKMS build.

### Read-only check

```bash
PROFILE_REF=<reviewed-ref-or-sha>
bash <(curl -fsSL "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/$PROFILE_REF/digitalhouses_pve_agent/hardware/beelink/install.sh") --check
```

From a reviewed local checkout:

```bash
sudo bash digitalhouses_pve_agent/hardware/beelink/install.sh --check
```

A healthy host ends with:

```text
CHECK=PASS
```

The check validates DMI, current-kernel DKMS installation, module resolution,
autoload, loaded driver version, IT8613E hwmon and the App collector when the App
is present.

### Uninstall / rollback

```bash
PROFILE_REF=<reviewed-ref-or-sha>
bash <(curl -fsSL "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/$PROFILE_REF/digitalhouses_pve_agent/hardware/beelink/uninstall.sh")
```

From a reviewed local checkout:

```bash
sudo bash digitalhouses_pve_agent/hardware/beelink/uninstall.sh
```

The uninstaller removes only the DigitalHouses autoload file, the pinned DKMS
version and its `/usr/src` source directory. It does not touch the stock
Proxmox module.

If the custom module is currently loaded, it is deliberately left in memory
until reboot; a reboot returns the host to the normal stock module state.

Older installed PVE kernels are intentionally ignored: they are not future boot targets and driver incompatibility there must not block preparing the current or next kernel.
