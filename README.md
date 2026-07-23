# DigitalHouses Home Assistant Apps

Home Assistant Apps maintained by DigitalHouses.

- Repository: `https://github.com/DigitalHouses/home-assistant-apps`
- License for DigitalHouses source code: MIT
- Third-party software retains its own license terms.

## English

### Installation

1. Open **Settings → Apps → App store** in Home Assistant.
2. Open the menu in the upper-right corner.
3. Select **Repositories**.
4. Add:

   ```text
   https://github.com/DigitalHouses/home-assistant-apps
   ```

5. Close the repository dialog.
6. Find the required App in the store and install it.

### Included Apps

#### DigitalHouses Speedtest

Runs the official native Ookla Speedtest CLI, publishes a single MQTT device
through Home Assistant MQTT Discovery, monitors internet reachability, and
supports manual and scheduled tests.

Current public support:

- Home Assistant OS / supervised installation with the Apps subsystem
- `amd64`
- MQTT service exposed by the Home Assistant Supervisor

Documentation:

- [`digitalhouses_speedtest/README.md`](digitalhouses_speedtest/README.md)
- [`digitalhouses_speedtest/DOCS.md`](digitalhouses_speedtest/DOCS.md)
- [`examples/packages/internet_speedtest_package.yaml`](examples/packages/internet_speedtest_package.yaml)

The repository may contain multiple DigitalHouses Apps. Each App is stored in
its own folder while `repository.yaml` remains at the repository root.

---

## Русский

### Установка

1. Откройте в Home Assistant **Настройки → Дополнения → Магазин дополнений**.
2. Откройте меню в правом верхнем углу.
3. Выберите **Репозитории**.
4. Добавьте адрес:

   ```text
   https://github.com/DigitalHouses/home-assistant-apps
   ```

5. Закройте окно репозиториев.
6. Найдите нужное приложение в магазине и установите его.

### Доступные приложения

#### DigitalHouses Speedtest

Запускает официальный нативный Ookla Speedtest CLI, публикует единое MQTT-устройство
через Home Assistant MQTT Discovery, контролирует доступность интернета и
поддерживает ручные и периодические замеры.

Текущая публичная поддержка:

- Home Assistant OS / supervised-установка с подсистемой Apps
- архитектура `amd64`
- MQTT-сервис, предоставленный Home Assistant Supervisor

Документация:

- [`digitalhouses_speedtest/README.md`](digitalhouses_speedtest/README.md)
- [`digitalhouses_speedtest/DOCS.md`](digitalhouses_speedtest/DOCS.md)
- [`examples/packages/internet_speedtest_package.yaml`](examples/packages/internet_speedtest_package.yaml)

В одном репозитории можно размещать несколько приложений DigitalHouses.
Каждое приложение хранится в своей папке, а общий `repository.yaml` находится
в корне репозитория.
