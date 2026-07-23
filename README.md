[README.md](https://github.com/user-attachments/files/30324986/README.md)
# DigitalHouses Home Assistant Apps

A collection of Home Assistant Apps maintained by DigitalHouses.

Repository URL:

```text
https://github.com/DigitalHouses/home-assistant-apps
```

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
6. Find the required DigitalHouses App and install it.

### Available Apps

#### DigitalHouses Speedtest

Internet availability monitoring and scheduled speed tests using the official Ookla Speedtest CLI.

Features include:

- download, upload, ping and jitter;
- internet connectivity checks;
- manual and periodic tests;
- preferred Ookla server selection;
- Home Assistant MQTT Discovery;
- optional Recorder package for history and analysis.

Documentation:

- [DigitalHouses Speedtest README](digitalhouses_speedtest/README.md)
- [DigitalHouses Speedtest documentation](digitalhouses_speedtest/DOCS.md)
- [Recorder package example](examples/packages/internet_speedtest_package.yaml)

### Repository structure

This repository can contain multiple Home Assistant Apps. Each App is stored in its own folder.

```text
home-assistant-apps/
├── repository.yaml
├── README.md
├── digitalhouses_speedtest/
├── examples/
└── ...
```

### License

DigitalHouses source code is licensed under the MIT License.

Third-party software used by individual Apps retains its own license terms.

---

## Русский

### Установка

1. Откройте в Home Assistant **Настройки → Дополнения → Магазин дополнений**.
2. Откройте меню в правом верхнем углу.
3. Выберите **Репозитории**.
4. Добавьте:

   ```text
   https://github.com/DigitalHouses/home-assistant-apps
   ```

5. Закройте окно репозиториев.
6. Найдите нужное приложение DigitalHouses и установите его.

### Доступные приложения

#### DigitalHouses Speedtest

Контроль доступности интернета и периодические замеры скорости с использованием официального Ookla Speedtest CLI.

Основные возможности:

- download, upload, ping и jitter;
- проверки доступности интернета;
- ручные и периодические тесты;
- выбор предпочтительных серверов Ookla;
- Home Assistant MQTT Discovery;
- дополнительный пакет Recorder для истории и анализа.

Документация:

- [README DigitalHouses Speedtest](digitalhouses_speedtest/README.md)
- [Документация DigitalHouses Speedtest](digitalhouses_speedtest/DOCS.md)
- [Пример пакета Recorder](examples/packages/internet_speedtest_package.yaml)

### Структура репозитория

В одном репозитории можно размещать несколько приложений Home Assistant. Каждое приложение находится в своей папке.

```text
home-assistant-apps/
├── repository.yaml
├── README.md
├── digitalhouses_speedtest/
├── examples/
└── ...
```

### Лицензия

Исходный код DigitalHouses распространяется по лицензии MIT.

Стороннее программное обеспечение, используемое отдельными приложениями, сохраняет собственные лицензионные условия.
