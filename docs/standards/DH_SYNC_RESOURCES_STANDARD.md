# DigitalHouses — DH Sync Resources Standard

**Current contract: DH Sync 0.6.0.** Supersedes prior dashboard routing, local view adoption and migration rules.

## 1. Registry and sources

The sole product registry is retained MQTT `DigitalHouses/Global/+/sync` and `DigitalHouses/Global/+/+/sync`. It contains only product identity and GitHub source location. Existing MQTT `dashboard` fields are ignored.

The single source-admission rule is GitHub owner `DigitalHouses`. No product allowlist, `availability` requirement, version gate, manual approval, or product-side UI registration.

GitHub is the canonical source for both product resources and panel layout. DH Sync checks on MQTT changes and hourly, then applies changed content. Version comments are informational only.

## 2. Canonical files

```text
digitalhouses_sync_app/dashboards/
  dh-system.yaml                   # Dashboard metadata and ordered View references
  dh-home.yaml                     # Optional future panel
<product_path>/
  dashboards/ru/*.yaml             # Standalone Home Assistant Lovelace Views
  packages/common/*.yaml          # Portable packages
  packages/locales/ru/*.yaml      # Portable Russian notifications
  examples/**                      # Ignored
```

One panel YAML file is one Dashboard. Its basename is the HA URL: `dh-system.yaml` → `/dh-system/`. The Dashboard is an item in the HA sidebar; a View is its top tab; Sections are card groups inside a View.

## 3. Panel YAML

```yaml
title: DH System
icon: mdi:server
show_in_sidebar: true
require_admin: true

views:
  - product: digitalhouses_pve_agent
    path: dh_pve_agent
    icon: mdi:server
    show_icon_and_title: false

  - product: digitalhouses_internet_app
    path: internet
    title: Internet
    icon: mdi:web
    show_icon_and_title: true
```

Rules:
- **Order of the `views` list is the tab order.** No `order` or separate sorting.
- `product + path` identifies a canonical View, and the product must be present in retained MQTT. Missing products/resources are simply not displayed.
- The same canonical View may appear in multiple panel YAML files, with independent tab title/icon presentation.
- Native HA View fields `title`, `icon` and `show_icon_and_title` may be overridden per placement; omit `icon` to inherit from the View, or use `icon: null` to show title only.
- `require_admin` is explicit for every panel. For user-facing summary content, publish a separate reduced View within the owning product; do not expose an admin View in a public panel.
- Two Views with the same `path` cannot coexist in one panel; identical paths across different panels are fine.
- All other fields and Sections/Cards remain native Lovelace YAML owned by the product.

## 4. Applying in Home Assistant

DH Sync reads product Views from GitHub and publishes their contents into its declared **Storage dashboards** through the official HA WebSocket API. It updates dashboard title, icon, sidebar visibility, admin restriction and ordered Views when YAML changes. No local copies of Views are required and no direct `.storage` edits are made.

Packages are still installed under `/config/packages/dh/` (or updated in their existing `/config/packages/` location by package key), with atomic writes and backups. DH Sync configures `homeassistant.packages: !include_dir_merge_named packages/` when necessary and asks HA for a quick YAML reload. Some integrations require a normal restart; DH Sync never restarts HA.

**No legacy migration.** Older YAML panels, local View files and unrelated manually maintained dashboards are not adopted or automatically removed. A declared Storage dashboard at the same URL is updated from new YAML; an existing YAML-mode dashboard cannot be managed by the Storage API.

Changes in GitHub are deployed automatically with no Apply confirmation. The Git commit history provides versioning and rollback of source files.
