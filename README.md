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
4. Add the repository URL shown above.
5. Close the repository dialog.
6. Find the required DigitalHouses App and install it.

### Available Apps

#### DigitalHouses Speedtest

Internet availability monitoring and scheduled speed tests using the official Ookla Speedtest CLI.

Key features:

- download, upload, ping, jitter and packet loss;
- internet connectivity checks;
- manual and periodic tests;
- live periodic-interval control from Home Assistant;
- preferred Ookla server selection;
- configurable performance thresholds;
- problem binary sensors;
- persistent recent successful results;
- Home Assistant MQTT Discovery;
- optional Recorder and Lovelace examples.

Documentation:

- [DigitalHouses Speedtest README](digitalhouses_speedtest/README.md)
- [DigitalHouses Speedtest documentation](digitalhouses_speedtest/DOCS.md)
- [Recorder package](examples/packages/internet_speedtest_package.yaml)
- [Lovelace dashboard](examples/lovelace/internet_speedtest_dashboard.yaml)

Questions and user experience belong in
[GitHub Discussions](https://github.com/DigitalHouses/home-assistant-apps/discussions).
Confirmed bugs and feature requests belong in
[GitHub Issues](https://github.com/DigitalHouses/home-assistant-apps/issues).



## Support the project

DigitalHouses projects are developed independently and provided free of charge.

If this project is useful to you, you can support its continued development, testing, maintenance, and documentation:

[![Support DigitalHouses on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/digitalhouses)

Support is entirely optional. All public features remain available to everyone.

## Русский

### Установка

1. Откройте **Настройки → Дополнения → Магазин дополнений**.
2. Откройте меню в правом верхнем углу.
3. Выберите **Репозитории**.
4. Добавьте URL репозитория, указанный выше.
5. Закройте окно репозиториев.
6. Найдите нужное приложение DigitalHouses и установите его.

### Доступные приложения

#### DigitalHouses Speedtest

Контроль доступности интернета и периодические измерения с официальным Ookla Speedtest CLI.

Основные возможности:

- download, upload, ping, jitter и packet loss;
- независимые проверки доступности интернета;
- ручные и периодические тесты;
- изменение интервала периодических тестов прямо в Home Assistant;
- приоритетные серверы Ookla;
- регулируемые пороги качества;
- problem binary sensors;
- постоянная история последних успешных тестов;
- Home Assistant MQTT Discovery;
- примеры Recorder и Lovelace.

Документация:

- [README DigitalHouses Speedtest](digitalhouses_speedtest/README.md)
- [Подробная документация](digitalhouses_speedtest/DOCS.md)
- [Пакет Recorder](examples/packages/internet_speedtest_package.yaml)
- [Панель Lovelace](examples/lovelace/internet_speedtest_dashboard.yaml)

Вопросы и пользовательский опыт публикуйте в
[GitHub Discussions](https://github.com/DigitalHouses/home-assistant-apps/discussions).
Подтверждённые ошибки и запросы функций — в
[GitHub Issues](https://github.com/DigitalHouses/home-assistant-apps/issues).

## Repository structure

```text
home-assistant-apps/
├── repository.yaml
├── README.md
├── digitalhouses_speedtest/
├── examples/
└── scripts/
```

## License

DigitalHouses source code is licensed under the MIT License.
Third-party software retains its own license terms.
