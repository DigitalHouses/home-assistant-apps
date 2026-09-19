# DH PVE Beelink IT8613E host setup design

Date: 2026-09-20

## Status

Approved for implementation.

## Problem

On the validated Beelink/AZW mini PC, Linux fan RPM is exposed only when the
newer upstream `frankcrawford/it87` driver is loaded. A manually built module
worked and exposed the IT8613E device, including the real `fan2_input`, but it
was not installed through DKMS and was not configured for boot autoload. After
a host reboot the module disappeared, `/sys/class/hwmon` had no fan inputs and
`dh_pve_app` therefore correctly removed fan RPM from its live inventory.

The App must not work around a missing kernel telemetry source. Host enablement
belongs to the Proxmox host.

## Goal

Provide a repository-owned, repeatable, idempotent Beelink hardware profile that
prepares Proxmox VE end-to-end using normal Debian/Proxmox mechanisms.

## Scope

The profile lives under:

```text
dh_pve_app/hardware/beelink/
```

It is separate from the generic `dh_pve_app/install.sh`. It is never executed
automatically for arbitrary Proxmox hosts.

## Source contract

Pinned upstream source:

- repository: `frankcrawford/it87`;
- commit: `bc06d3488439e5fcd725c1bdcfcac994d6d95cac`;
- module version: `v2.0-4-gbc06d34.20260913`.

The installer downloads only the required source files from
`raw.githubusercontent.com` because this deployment environment has previously
had direct `github.com:443` connectivity failures while raw GitHub content was
reachable.

Each source file is verified using its pinned Git blob SHA before it is copied
to `/usr/src`.

## Native system integration

The installer uses:

- APT for `dkms`, build tools and Proxmox headers;
- `/usr/src/it87-<version>` for DKMS source;
- DKMS registration plus build/install for the running PVE kernel and every newer installed PVE kernel that has a matching headers tree, including any already-installed next boot kernel;
- `depmod` for module dependency resolution;
- `/etc/modules-load.d/digitalhouses-beelink-it87.conf` for boot autoload;
- normal `modprobe it87` for activation.

The stock Proxmox `it87` module is never replaced, deleted or edited.

## Hardware guard

Installation is fail-closed:

1. must run as root;
2. `pveversion` must exist;
3. DMI identity must contain a supported vendor marker: `AZW` or `Beelink`;
4. after activation, hwmon must expose chip name `it8613`;
5. `fan2_input` must exist and be numeric.

No `force_id`, `fix_pwm_polarity`, `ignore_resource_conflict`, direct
`insmod`, direct `rmmod` or PWM manipulation is allowed.

## Runtime verification

If `dh_pve_app` is installed, the installer invokes the App's real
`collect_fans()` collector and requires the stable hardware ID
`it8613_it87_2608_fan2`.

The hardware profile does not restart or reconfigure `dh_pve_app`; the normal
FAST collection loop observes the restored hwmon source.

## Idempotency

A repeated install:

- revalidates the host;
- repairs required packages and source files;
- discovers the running kernel and every newer installed PVE kernel with matching headers and ensures the pinned DKMS build is installed for each one before reboot;
- preserves matching installed DKMS builds;
- repairs the autoload file;
- activates the module only when it is not already loaded.

If another `it87` build is already loaded, the installer does not unload it on
a live Proxmox host. Persistent installation completes and the script reports
that one reboot is required.

## Read-only mode

`install.sh --check` performs no writes. It validates:

- host identity;
- running-kernel headers and the installed PVE kernel/header set;
- DKMS status for every current/newer discovered target kernel;
- modprobe resolution;
- autoload configuration;
- loaded module version;
- IT8613E hwmon;
- App collector visibility when available.

## Rollback

`uninstall.sh` removes only:

- the DigitalHouses modules-load file;
- the pinned DKMS version;
- its matching `/usr/src` tree.

The stock Proxmox driver is not touched. A currently loaded custom module is
left in memory until reboot rather than forcibly removed from a running host.

## Test contract

Repository tests must reject changes that:

- unpin the upstream commit/source hashes;
- replace the stock kernel module;
- introduce unsafe module parameters or direct `insmod`/`rmmod`;
- remove DKMS or modules-load integration;
- remove hardware/runtime verification;
- make the scripts non-executable.

GitHub Actions also runs `bash -n` on both hardware scripts.

Older installed PVE kernels are intentionally ignored: they are not future boot targets and driver incompatibility there must not block preparing the current or next kernel.
