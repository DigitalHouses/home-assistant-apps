# Internet App — контролируемая миграция HA App slug

Статус: завершена и выведена из текущего runtime.

Канонический продукт:

```text
digitalhouses_internet_app
```

Миграция:

```text
legacy HA App slug:    digitalhouses_internet
canonical target slug: digitalhouses_internet_app
```

Каталог репозитория и product/release/telemetry identities уже канонические. MQTT и Home Assistant identities остаются `dh_internet_app`; эта миграция меняет только Supervisor App identity.

Миграция завершена и принята на канонической установке. Версия `0.1.16` удалила временный migration runtime, writable mapping `/share` и migration environment mode из текущего App. Этот документ сохранён как историческая запись миграции; релизы `0.1.12`–`0.1.15` содержат реализацию, использованную в переходный период.

## Почему это контролируемая переустановка

Home Assistant Supervisor привязывает установленный App и его persistent `/data` к App slug. Поэтому изменение `config.yaml -> slug` создаёт другой установленный App, а не переименовывает существующий.

Миграция не должна зависеть от копирования Docker/container internals и не должна создавать новые MQTT или Home Assistant entity identities.

## Фаза 1 — bridge release

Последний релиз со старым slug:

```text
digitalhouses_internet
```

монтирует Home Assistant `/share` в режиме read-write и автоматически записывает:

```text
/share/digitalhouses_internet_app/slug-migration-v1/bundle.tar.gz
```

Bundle создаётся атомарно, с mode 0600 там, где это поддерживается, и содержит только явный persistent contract:

```text
/data/options.json
/data/telemetry.json
/data/runtime/outages.json
/data/runtime/speedtest.json
/data/runtime/thresholds.json
/data/runtime/traffic.json
/data/runtime/recent_results.json
/data/runtime/servers.json
/data/runtime/recovery.json
/data/runtime/discovery.json
```

Отсутствие optional state files допускается. `options.json` обязателен.

Bridge обновляет bundle при startup и повторно при graceful shutdown. Shutdown snapshot является source of truth миграции.

Manifest фиксирует:

- канонический product ID;
- source и target slug;
- bridge App version;
- export timestamp;
- точный список файлов, размеры и SHA-256 hashes;
- best-effort Supervisor settings: boot mode, auto-update и watchdog.

## Фаза 2 — релиз с каноническим slug

Версия `0.1.13` стала первым релизом с каноническим slug. Версия `0.1.14` исправила последовательность import с учётом реального lifecycle Supervisor options. Версия `0.1.15` сделала completed migration state authoritative после того, как rollback обновляет shared bridge bundle. Канонический App использует:

```yaml
slug: digitalhouses_internet_app
```

В migration window канонические релизы сохраняли migration mapping `/share` и запускались с `DH_SLUG_MIGRATION_MODE=import`. Эти временные controls были удалены в `0.1.16` после acceptance.

До запуска обычного runtime App:

1. обнаруживает bridge bundle;
2. проверяет product, source slug, target slug, member allowlist и каждый SHA-256;
3. сравнивает mounted `/data/options.json` с options из bridge;
4. если они различаются, применяет старые options через `/addons/self/options`, записывает options-pending marker и корректно останавливается;
5. при следующем запуске проверяет, что Supervisor смонтировал ожидаемые options;
6. атомарно восстанавливает всё остальное App-owned state;
7. записывает completed import marker в новом `/data`;
8. запускает обычный Internet App runtime.

Если options уже были сохранены неудачной попыткой `0.1.13`, версия `0.1.14` обнаруживает это состояние и сразу продолжает final import без повторного применения options.

Успешно завершённая миграция никогда не применяется дважды. После появления валидного completed marker канонический App полностью игнорирует последующие изменения bridge bundle; это необходимо, потому что rollback start/stop legacy `0.1.12` пересоздаёт shared bundle с новым timestamp/hash.

Свежая каноническая установка запускается обычно. Начиная с `0.1.16` production runtime больше не обрабатывает migration bundle.

## Telemetry identity

`/data/telemetry.json` копируется byte-for-byte. Поэтому App с каноническим slug сохраняет те же:

- `installation_id`;
- installation token;
- telemetry enable state;
- last success/attempt scheduling state.

Новая product version после миграции всё равно сообщается штатно, потому что telemetry client обнаруживает изменение release version.

## Историческая последовательность оператора

1. Обновить App со старым slug до bridge release.
2. Убедиться по bridge log, что migration bundle готов.
3. Создать Home Assistant backup, пока legacy App ещё установлен.
4. Остановить legacy App. Не удалять его.
5. Убедиться по shutdown log, что migration bundle обновлён.
6. Перезагрузить App Store и установить/обновить App с каноническим slug `digitalhouses_internet_app` до версии `0.1.15`.
7. Запустить его. Если log сообщает, что migrated options применены и требуется restart, запустить App ещё раз. Затем убедиться, что log сообщает об успешном import bundle до запуска обычного runtime.
8. Проверить options, telemetry identity, Internet state, thresholds, outage/traffic history и HA/MQTT entities.
9. Один раз перезапустить канонический App и убедиться, что bundle повторно не импортируется.
10. Создать backup App с каноническим slug и проверить restore.
11. Один раз доказать rollback: остановить канонический App и запустить всё ещё установленный legacy bridge App, затем снова остановить legacy и вернуться на canonical. Legacy bridge обновит shared bundle; canonical обязан проигнорировать его, потому что миграция уже завершена.
12. Только после acceptance удалить остановленный legacy App.

Два App никогда не должны работать одновременно, поскольку они намеренно используют одни и те же MQTT client/device/entity identities.

## Исторический rollback

До acceptance rollback намеренно простой:

1. остановить App с каноническим slug;
2. запустить всё ещё установленный legacy bridge App.

Миграция MQTT/entity не требуется, потому что оба релиза используют один namespace `dh_internet_app`.

Home Assistant backup до миграции является disaster-recovery protection, а не основным механизмом немедленного rollback.

## Зафиксированные критерии acceptance

Миграция считается завершённой только после проверки:

- установлен канонический App slug;
- во время проверки legacy App остаётся остановленным;
- options совпадают с bridge export;
- всё явное state `/data` восстановлено;
- telemetry installation ID/token не изменились;
- на server side не появилось duplicate telemetry installation;
- существующие `dh_internet_app_*` entities сохранили прежние identities;
- новый backup канонического slug успешно восстанавливается;
- rollback на остановленный bridge App доказан до удаления legacy App.

## Cleanup release

Версия `0.1.16` завершила cleanup миграции:

- удалён writable mapping `/share`;
- удалён `DH_SLUG_MIGRATION_MODE`;
- удалены `slug_migration.py` и migration-only tests;
- из shutdown удалены bridge export hooks;
- канонический slug `digitalhouses_internet_app` оставлен единственным поддерживаемым текущим App identity;
- MQTT/device/entity identities под `dh_internet_app` сохранены без изменений.
