from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEELINK = ROOT / "hardware" / "beelink"
INSTALLER = BEELINK / "install.sh"
UNINSTALLER = BEELINK / "uninstall.sh"
README = BEELINK / "README.md"

IT87_REPOSITORY = "https://github.com/frankcrawford/it87.git"
IT87_COMMIT = "bc06d3488439e5fcd725c1bdcfcac994d6d95cac"
IT87_VERSION = "v2.0-4-gbc06d34.20260913"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_beelink_hardware_profile_files_exist_and_are_executable():
    assert INSTALLER.is_file()
    assert UNINSTALLER.is_file()
    assert README.is_file()
    assert INSTALLER.stat().st_mode & 0o111
    assert UNINSTALLER.stat().st_mode & 0o111


def test_beelink_installer_pins_known_good_it87_source():
    text = _text(INSTALLER)

    assert 'IT87_RAW_BASE="https://raw.githubusercontent.com/frankcrawford/it87"' in text
    assert 'IT87_COMMIT="bc06d3488439e5fcd725c1bdcfcac994d6d95cac"' in text
    assert 'IT87_VERSION="v2.0-4-gbc06d34.20260913"' in text
    assert 'IT87_C_SHA="74e790fd9c437df1bee20ab7c5d92e7e186fd1d3"' in text
    assert 'COMPAT_H_SHA="d6485c20dae9135df6a79d009f5eca2422886461"' in text
    assert 'MAKEFILE_SHA="5b040b64ee1c7b421b87510b92f6da25bac4a5f3"' in text
    assert 'DKMS_CONF_SHA="bb6e28058ee35c438618fe167695db9f853469c2"' in text
    assert 'git_blob_sha' in text
    assert 'raw.githubusercontent.com' in text


def test_beelink_installer_uses_native_proxmox_dkms_pipeline():
    text = _text(INSTALLER)

    for token in (
        "proxmox-default-headers",
        "proxmox-headers-${KERNEL}",
        "dkms",
        'DKMS_SOURCE="/usr/src/it87-${IT87_VERSION}"',
        'dkms add -m it87 -v "${IT87_VERSION}"',
        'dkms build -m it87 -v "${IT87_VERSION}" -k "$target_kernel"',
        'dkms install -m it87 -v "${IT87_VERSION}" -k "$target_kernel"',
        'depmod -a "$target_kernel"',
        'modprobe it87',
        "/etc/modules-load.d/digitalhouses-beelink-it87.conf",
    ):
        assert token in text


def test_beelink_installer_never_replaces_stock_kernel_module_or_uses_unsafe_overrides():
    text = _text(INSTALLER)

    forbidden = (
        "force_id=",
        "fix_pwm_polarity=",
        "ignore_resource_conflict=",
        "/kernel/drivers/hwmon/it87.ko",
        "insmod ",
        "rmmod ",
    )
    for token in forbidden:
        assert token not in text


def test_beelink_installer_is_fail_closed_and_idempotent():
    text = _text(INSTALLER)

    assert '[[ "${EUID}" -eq 0 ]]' in text
    assert "pveversion" in text
    assert "/sys/class/dmi/id/sys_vendor" in text
    assert "/sys/class/dmi/id/product_name" in text
    assert '"AZW"' in text
    assert '"Beelink"' in text
    assert 'dkms status -m it87 -v "${IT87_VERSION}"' in text
    assert "already installed" in text
    assert "--check" in text


def test_beelink_installer_verifies_real_hwmon_and_app_collector():
    text = _text(INSTALLER)

    assert 'name" = "it8613"' in text
    assert "fan2_input" in text
    assert "collect_fans" in text
    assert "it8613_it87_2608_fan2" in text


def test_beelink_uninstaller_only_removes_digitalhouses_dkms_profile():
    text = _text(UNINSTALLER)

    assert 'IT87_VERSION="v2.0-4-gbc06d34.20260913"' in text
    assert "/etc/modules-load.d/digitalhouses-beelink-it87.conf" in text
    assert 'dkms remove -m it87 -v "${IT87_VERSION}" --all' in text
    assert 'rm -rf "/usr/src/it87-${IT87_VERSION}"' in text

    for token in (
        "/kernel/drivers/hwmon/it87.ko",
        "force_id=",
        "fix_pwm_polarity=",
    ):
        assert token not in text


def test_beelink_readme_documents_scope_reboot_and_stock_module_preservation():
    text = _text(README)

    for token in (
        "Beelink",
        "AZW",
        "IT8613E",
        "DKMS",
        "reboot",
        "stock",
        "bc06d3488439e5fcd725c1bdcfcac994d6d95cac",
    ):
        assert token in text


def test_beelink_installer_renders_dkms_version_without_fragile_sed_quoting():
    text = _text(INSTALLER)

    assert 'render_dkms_conf' in text
    assert 'awk -v version="${IT87_VERSION}"' in text
    assert 'sed -i "s/^PACKAGE_VERSION=' not in text


def test_beelink_installer_cleanup_is_safe_with_nounset_after_function_return():
    text = _text(INSTALLER)

    assert 'TMP_DIR=""' in text
    assert 'cleanup()' in text
    assert 'trap cleanup EXIT' in text
    assert 'trap \'rm -rf "$tmp"\' EXIT' not in text


def test_beelink_installer_builds_for_all_installed_pve_kernels_with_headers():
    text = _text(INSTALLER)

    assert 'discover_target_kernels' in text
    assert '/lib/modules/*-pve' in text
    assert 'for target_kernel in "${TARGET_KERNELS[@]}"' in text
    assert 'dkms build -m it87 -v "${IT87_VERSION}" -k "$target_kernel"' in text
    assert 'dkms install -m it87 -v "${IT87_VERSION}" -k "$target_kernel"' in text
