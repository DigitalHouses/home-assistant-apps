# PVE Agent — стандартный тест батареи NUT

Дата: 04.10.2026. Версия исходников: 0.5.52.

## Причина изменения

У распространённых SNMP UPS MIB в NUT 2.8.5 используются разные команды: CyberPower RMCARD, APC, MGE/Eaton и Compaq предоставляют `test.battery.start`; Eaton Power Xpert — `test.battery.start.quick`; стандарт IETF UPS-MIB определяет отдельные General Systems Test, Quick Battery Test и Deep Battery Calibration.

RFC 1628 не гарантирует длительность или глубину разряда для общего теста. Поэтому `test.battery.start` **не является универсальным эквивалентом Quick**.

## Единый контракт, без условий по производителям

- `test.battery.start` — Standard Test, ручная кнопка `button.dh_pve_agent_ups_test_standard`, бинарник `binary_sensor.dh_pve_agent_ups_standard_test_supported`.
- `test.battery.start.quick` — прежний Quick Test, включая расписание.
- `test.battery.start.deep` — прежний Deep Test, включая расписание.
- `test.battery.stop` — прежняя кнопка Stop при наличии команды.
- `calibrate.*`, `test.failure.*`, `shutdown.*` и `load.*` не включаются в перечень команд тестирования.

Возможность определяется только точным именем команды в `upscmd -l` и наличием разрешённых NUT command credentials. Имя производителя, модель, OID и тип подключения (USB/SNMP) не проверяются.

Новый Standard Test **не включён в расписания**: запуск строго вручную, длительность и последствия определяются конкретным UPS, а не предполагаются агентом. Устройство UPS в Home Assistant остаётся одним и тем же.

MQTT: `<ups-base>/test/standard`, payload `PRESS`, retained-команды отвергаются. Для исполнения используется уже существующий список разрешённых действий, журнал и история тестов с типом `Standard`. Политика FSD, NUT и остановка PVE не меняются.

Тесты программной реализации используют заглушки; физический тест UPS не выполняется.

Источники: NUT 2.8.5 `drivers/apc-mib.c`, `cyberpower-mib.c`, `mge-mib.c`, `compaq-mib.c`, `eaton-ups-pwnm2-mib.c`, `ietf-mib.c`; RFC 1628.
