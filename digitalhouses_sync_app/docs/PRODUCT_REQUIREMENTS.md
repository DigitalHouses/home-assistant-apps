# DH Sync v1 — требования к разработчикам DigitalHouses Apps/Agents

**Статус:** проект контракта для поэтапного внедрения.  
**Владелец контракта доставки YAML:** DigitalHouses Sync App.  
**Область:** все поддерживаемые продукты в `DigitalHouses/home-assistant-apps`, независимо от типа `haos_addon` / `linux_agent`.  
**Приоритет пилота:** `digitalhouses_pve_agent` (две вкладки: Proxmox и Электропитание).

## 1. Цель

Дать `digitalhouses_sync_app` возможность одинаковым способом определить установленный продукт и его версию, получить совместимые канонические Home Assistant dashboards/packages из GitHub и собрать одну панель `DigitalHouses`. За содержимое YAML отвечает команда **своего** продукта. DH Sync не устанавливает и не обновляет исполняемый код продуктов.

**Не меняйте** ради DH Sync MQTT namespaces, `unique_id`, `entity_id`, device identifiers, существующие Recorder и notification contracts, service names, логику аварийного выключения, app slugs или системные каталоги.

## 2. Обязательные действующие стандарты

Это ТЗ **дополняет**, а не заменяет:

- `docs/standards/DIGITALHOUSES_APP_STANDARD.md` — тип `digitalhouses.app`, диагностика Version/Started at, test/CI;
- `docs/standards/PRODUCT_NAMING_STANDARD.md` — реестровая identity;
- `docs/standards/HA_PACKAGE_VERSIONING_STANDARD.md` — версия каждого распространяемого package;
- `docs/standards/EVENTS_AND_NOTIFICATIONS_STANDARD.md` — machine events и локальная доставка;
- `docs/standards/REPOSITORY_GOVERNANCE.md` — PR, тесты;
- `docs/standards/RELEASE_POLICY.md` и `IMMUTABLE_DELIVERY_AND_TELEMETRY_STANDARD.md` — релиз и provenance.

Не создавайте второй реестр product identity и не дублируйте уже закреплённые metadata под другим названием.

## 3. GitHub: единый каталог ресурсов **внутри** существующего каталога продукта

Пример для PVE (точные имена файлов по окончании миграции зафиксирует команда PVE):

```text
digitalhouses_pve_agent/
  dashboards/
    ru/
      10_pve_proxmox.yaml
      11_pve_ups.yaml
    en/
      10_pve_proxmox.yaml
      11_pve_ups.yaml
  packages/
    common/
      dh_pve_agent_package.yaml
    locales/
      ru/
        dh_pve_agent_notification_local_package.yaml
      en/
        dh_pve_agent_notification_local_package.yaml
```

- `dashboards/<locale>/*.yaml`: **один самостоятельный Lovelace view на файл**; содержимое — HA view, а не dashboard wrapper или Markdown snippet. Уникальный `path` обязателен, порядок задан префиксами `10_`, `11_` и т.п.
- `packages/common/*.yaml`: глобальные helpers, Recorder/Logbook, scripts и автоматики без привязки к дому.
- `packages/locales/<locale>/*.yaml`: локализованные notifications и иной текст; **не** клиентские адресаты/секреты/частные IP.
- У продукта могут быть только packages, только views или ни того ни другого. Не создавать пустые примеры ради формального соблюдения.
- Для public-ready продукта публикуйте `en` и `ru`, если UI использует текст. Для ещё не подготовленной локали **не делать пустой фиктивный перевод**: сообщить о gap.
- Уже существующие `examples/` и пользовательские рабочие копии сохранять до отдельной подтверждённой миграции. Не удалять и не подменять их автоматически.

## 4. Метаданные ресурсов без проверки совместимости

**Для HA packages** использовать уже обязательный формат из `HA_PACKAGE_VERSIONING_STANDARD.md`:

```yaml
# DH-Package: dh_pve_agent_package
# DH-Package-Version: 1.0.0
# DH-Package-Date: 2026-11-13
```

**Для каждого нового canonical Lovelace view** предлагаем минимальный comment header (контракт DH Sync; не YAML-сущности):

```yaml
# DH-View: dh_pve_agent
# DH-View-Version: 1.0.0
# DH-View-Date: 2026-11-13
title: Proxmox
path: dh_pve_agent
type: sections
```

DH Sync не использует диапазоны `DH-Compatible-*`: не добавляйте их в канонические YAML. Единственный критерий допуска источника — владелец GitHub `DigitalHouses`. Версии продукта, view и package показываются как сведения, но не используются для допуска.

**Разные независимые версии:** App/Agent release, view revision, package revision. Не изменять версию исполняемого продукта из-за одной правки dashboard.

DH Sync при каждом явном read-only просмотре разрешает default branch в конкретный Git commit SHA и использует только его для текущего набора файлов. Такой SHA не является allowlist и не подтверждает совместимость.

## 5. MQTT: установка, доступность и версия

Для новых релизов, обнаруживаемых через DH Sync, используется **Discovery Contract v1**:
[DH_SYNC_DISCOVERY_CONTRACT_V1.md](DH_SYNC_DISCOVERY_CONTRACT_V1.md).

Продукт самостоятельно публикует retained QoS1 JSON со своим `product_id`,
`type`, `version`, `repository`, `product_path`. DH Sync проверяет
**точного владельца GitHub `DigitalHouses`**, а не строковый префикс.
Это самообновляемый источник описания продукта, **не разрешение на установку**.
Действующий availability и MQTT Discovery не переименовывать; продукты без
новой карточки остаются доступными через legacy-инвентаризацию пилота.


Каждая команда обязана указать в документации своего продукта:

1. стабильный `product_id`, совпадающий с продуктом в MQTT `/sync` topic;
2. существующий **product-level** MQTT availability topic с `online` / `offline`, retained publish и Last Will, либо зафиксированный gap;
3. реальный MQTT Discovery device/topic и диагностический Version sensor, получающий версию из того же источника, что и release;
4. стабильный Started-at sensor по общему стандарту, если его ещё нет;
5. поведение при перезапуске, временной потере MQTT и uninstall.

**Для v1 не требуется новый универсальный heartbeat.** Используем существующие `availability` и MQTT Discovery. Топики подсистем (UPS, Plex API, database, result availability) не являются доказательством установки/удаления всего продукта.

У DH Sync сохраняется локальная запись о продукте после достоверного обнаружения. Отсутствие или `offline` не равно uninstall. **Не посылать автоматические события удаления из-за потери связи.**

Если существующая availability не соответствует retained/LWT, доработать **свой** продукт **без переименования уже выпущенных публичных топиков**. Для uninstall в v1 допустима подтверждённая пользователем операция DH Sync; отдельный tombstone protocol не навязывать всем продуктам сейчас.

## 6. Dashboards: что проверить разработчику

- View работает как автономный `type: sections` YAML, пригодный для `!include_dir_list`.
- Не включать `lovelace:` или глобальную регистрацию sidebar внутри собственного view/package. Единую панель регистрирует **только DH Sync**.
- Сохранить исходный `path`, `entity_id`, управление и динамические карточки.
- При `offline` агента вкладка остаётся и показывает соответствующее состояние.
- Отсутствующая необязательная подсистема (например, не настроенный UPS) **не скрывает вкладку целиком**.
- Перечислить frontend dependencies (Mushroom, auto-entities, mini-graph-card, button-card и др.) в README. DH Sync в v1 лишь предупреждает, **не устанавливает HACS**.
- Не исправлять рабочий дизайн только ради рефакторинга. Не добавлять привязки к конкретным IP, хостам, домам, климатическим сущностям клиентов.
- Для каждого динамического списка предусмотреть корректное пустое состояние; не терять History/Recorder из-за случайного переименования.

## 7. Packages: что проверить разработчику

- Каждое распространённое package имеет единый стабильный top-level key, версии/даты по существующему стандарту и не конфликтует с другими packages.
- Recorder/Logbook: сохранять используемые метрики и globs, убрать только проверенную устаревшую ссылку; новые entity IDs не выдумывать.
- Notifications: machine events от продукта и локализованные templates в HA. Не использовать частные `notify.*`, tokens, номера, IP в каноническом YAML; адресаты задаются отдельно локально.
- Сложные конфигурационные изменения должны иметь документацию о необходимом HA restart vs reload. Нельзя обещать hot reload всех packages.
- Запрещено автоматически перезапускать HA от имени продуктов или DH Sync ради развертывания package.

## 8. Удаление и миграция

- Удаление App/Agent и потеря доступности — разные события.
- При подтверждённом удалении DH Sync удалит **только свои управляемые** views/packages данного продукта, оставив резервную копию до проверки.
- Не стирать пользовательские packages или другие dashboard файлы вне управляемого дерева.
- Любая смена MQTT `entity_id`, Discovery identifiers, automation IDs, package keys требует отдельной миграции, review и тестов.
- Для уже установленного продукта нужна процедура «adopt» существующего YAML с предварительным сравнением и **без silent overwrite**.

## 9. Приёмка продуктовой команды

1. PR меняет **только каталог своего продукта** (и его product-specific тесты); общий стандарт/реестр — только по отдельному согласованию.
2. Есть canonical `dashboards/` и/или `packages/` по контракту, русская и английская локали или честно обозначенный gap.
3. Есть действующие metadata, версии, доказанный диапазон совместимости для автоматического обновления.
4. Подтверждены MQTT availability, Discovery, Version, Started at, LWT, offline/uninstall semantics.
5. Сохранены текущие сущности, Recorder, локальные notification adapters, UPS/NUT safety и dashboard behavior.
6. Проверены lint/YAML parser, product tests, существующий repository CI; указывать конкретные команды и результат.
7. В PR описаны исходные файлы, новый canonical путь, что было перенесено, какие есть gaps и какие риски.
8. **Не** обновлять рабочий HA, не устанавливать Sync App, не сливать чужие ветки и не менять код другого продукта.

## 10. Первая очередь — PVE Agent

Использовать только подтверждённый живой пилот v3:
- `10_pve_proxmox.yaml` с корректными FAN 1/FAN 3 и не сломанным графиком CPU/RAM/Swap/Fans;
- `11_pve_ups.yaml` без редизайна;
- основной package и локальные уведомления после аудита; `sensor.dh_pve_agent_gpu_*_transcoding` — проверить как устаревший Recorder glob, не удалять без оценки эффекта;
- две вкладки независимо от наличия настроенного UPS.

Старые `examples/dh_pve_agent_dashboard_ru.yaml` / UPS и другие snippets не считать v3. Если источники v3 не доступны команде, запросить архивы рабочего пилота, **не реконструировать на память**.

## 11. Что вернуть координатору DH Sync

В ответе разработчика обязательны: ссылка на PR/commit, `product_id`, актуальный `availability` topic, Version sensor, Started-at sensor, список новых YAML с версиями, статус EN/RU, результаты тестов, открытые gaps.

**Отдельно от DH Sync:** обновление исполняемого кода Apps/Agents, телеметрия внешнего stats-сервера, и внутренние пороги/датчики продуктов остаются в своих проектах.

