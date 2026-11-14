# DH Sync v0.1.0 — первый рабочий кандидат

**Статус: исходный код в Draft PR #499, образ GHCR ещё не опубликован.** Никаких автоматических изменений CORE/HOME.

## Что делает v0.1.0

Приложение HAOS продолжает наблюдать штатный MQTT availability; offline никогда не равен uninstall.
Встроенная admin-only Ingress панель показывает версии PVE/Plex Agent, источники Git, состояние трёх вкладок и ожидаемый план.
При запуске и MQTT reconnect приложение **не пишет YAML**.

Пользователь открывает панель, просматривает план, включает настройку **allow_changes: true** и подтверждает Apply. Для восстановления есть отдельное подтверждение Rollback.

## Пилот CORE

| Объект | Совместимость | Git commit | Файл на HA |
| --- | --- | --- | --- |
| Proxmox | PVE Agent 0.5.88 | 2b7a7857ab5fe2d4c8493faacbfd1b43518ed087 | /config/dashboards/dh/views/10_pve_proxmox.yaml |
| UPS | PVE Agent 0.5.88 | 2b7a7857ab5fe2d4c8493faacbfd1b43518ed087 | /config/dashboards/dh/views/11_pve_ups.yaml |
| Plex | Plex Agent 0.8.17 | d4e99ac789b6bd53c4185bff5427d315 | /config/dashboards/dh/views/12_plex.yaml |

PVE revision — пока голова Draft PR #502; перед общим релизом требуется принять PR и закрепить его merge commit. Plex revision — уже объединённый PR #500.

Панель должна быть зарегистрирована под URL-path **digital-houses** и содержать ui.yaml с директивой **views: !include_dir_list views/**.
CORE уже имеет такую панель. v0.1 не регистрирует новую панель, не редактирует configuration.yaml и не изменяет .storage.

## Строгие условия Apply

1. Версия обоих агентов запрашивается через Supervisor Core API из сенсоров sensor.dh_pve_agent_version и sensor.dh_plex_agent_version; при mismatch операция блокируется.
2. Все канонические YAML загружаются только по трём разрешённым путям из неизменяемых Git SHA.
3. Проверяются DH-View, DH-View-Version, DH-Compatible-Agent, type: sections, icon, path и отсутствие дубликатов в views и Lovelace Storage.
4. Под замену допускаются лишь точные исторические SHA-256 подтверждённых v3-файлов CORE или уже совпадающие ресурсы. Неизвестная локальная правка блокирует **всю** группу.
5. До любой записи проверяется конфигурация HA; сохраняются байты и атрибуты файлов, SHA и журнал транзакции под /data/sync-v01/transactions/.
6. Изменяются лишь перечисленные файлы. Каждая замена атомарна. Повторяется HA config check и WebSocket readback панели.
7. Если HA отказывается принять конфигурацию, восстанавливаются только файлы, которые сохранили ожидаемое состояние. При конфликте дальнейшая запись останавливается и сохраняется журнал для диагностики.
8. Откат выполняется явно и отказывается перезаписывать любые последующие пользовательские изменения.

## За пределами первой версии

- Ни одного нового Recorder/package или локальных notifications; установленный Plex Recorder сохраняется.
- Нет редактирования HA Storage, пересоздания sidebar, обновления исполняемых агентов и перезапуска HA.
- Нет автоматического фонового применения изменений, удаления при offline, массового развёртывания на другие дома.
- Нет установки HACS-зависимостей; необходимые HACS карточки должны существовать заранее.
- Отдельный Plex Storage migration prototype не запускается из Ingress v0.1.

## Права приложения

HAOS config содержит homeassistant_api: true, ingress: true, panel_admin: true, а mount homeassistant_config доступен для записи.
Это требуется для **отдельно разрешённого** применения. По умолчанию allow_changes: false, POST без явного пользовательского подтверждения запрещён.
Приложение обращается к HA только через Supervisor Core API с SUPERVISOR_TOKEN, выданным Supervisor; личный long-lived HA token не нужен.

## Обязательная приёмка перед публикацией

- [ ] CI, сборка App и тесты синтетического Apply/Rollback прошли.
- [ ] PR #502 рассмотрен; зафиксирован окончательный immutable source SHA.
- [ ] Опубликован отдельный проверенный образ GHCR 0.1.0.
- [ ] На CORE HA 192.168.11.242 проверены Ingress, версии, dry-run, отсутствие дубликатов и сохранение Plex.
- [ ] После ручного Apply отображаются иконки Proxmox/UPS и работают вентиляторы, графики, UPS.
- [ ] Проверен ручной Rollback с возвратом двух исходных файлов и их SHA.
- [ ] Проверены ошибки, пропадание MQTT, случайный local edit и пробный второй HA.
- [ ] Пройдены release/telemetry/privacy governance gates проекта.

**Зелёный CI сам по себе не является разрешением публиковать или устанавливать приложение.**

## Discovery Contract v1 (принятое развитие v0.1.0)

MQTT metadata продукта: `schema, product_id, type, version, repository, product_path`.
Сохранение и список заявленных источников реализованы, проверка GitHub owner
строгая: только `https://github.com/DigitalHouses/<repository>`, без подмены
host, userinfo, URL encoding, redirect URL, портов и traversal. В пилоте
это **только read-only обнаружение источников**. YAML Apply по новым
адресам из MQTT запрещён: текущий SyncEngine использует три pinned commit.

Подробности: [Discovery Contract v1](DH_SYNC_DISCOVERY_CONTRACT_V1.md).
