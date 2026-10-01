# DigitalHouses Internet App — план проверки HAOS

Этот план покрывает текущий канонический runtime DigitalHouses Internet App.

## 1. Безопасный первый запуск

Перед запуском App:

- укажите в `router_ip` фактический LAN-адрес роутера;
- оставьте `recovery.enabled: false`;
- оставьте пустыми все пять mappings `traffic.*`;
- для первого запуска установите `speedtest.periodic_enabled: false`;
- для начальной функциональной проверки оставьте `telemetry_enabled: false`;
- убедитесь, что MQTT service установлен и доступен Supervisor.

Ожидаемый результат после запуска:

- одно MQTT device с именем **DigitalHouses Internet App**;
- все созданные entity IDs используют префикс `dh_internet_app_`;
- Version совпадает с установленной released App version;
- Started at содержит корректный timestamp;
- connectivity Internet, Google, Cloudflare и Router обновляется штатно;
- ни одно recovery action не может выполниться.

## 2. Ручной Speedtest

Нажмите `button.dh_internet_app_run_speedtest`.

Проверьте:

- status меняется с `idle` на `running`, затем возвращается в `idle`;
- Download, Upload и Ping содержат числовые значения;
- Jitter и Packet loss заполняются, если Ookla их предоставляет;
- `last_result` становится `success`, а provider/server/result metadata появляются в Speedtest status;
- в Recent Results появляется одна запись.

Временно измените один порог так, чтобы последний результат его нарушал, затем верните исходное значение.

Проверьте:

- соответствующий problem binary меняется;
- aggregate Performance problem меняется;
- отправляются schema-v2 performance events;
- возврат порога очищает текущую проблему, не переписывая исторический snapshot Recent Results.

## 3. Каталог серверов

Нажмите `button.dh_internet_app_refresh_servers`.

Проверьте:

- операция выполняется только по запросу;
- Available servers получает новый timestamp и список серверов;
- в App log отсутствует периодический polling каталога серверов.

## 4. Отключение и persistence

При всё ещё выключенном Recovery создайте контролируемое отключение Интернета.

После настроенного количества неудачных проверок проверьте:

- Internet становится unavailable;
- появляется один активный outage текущего месяца;
- пока outage активен, у него `to: null`;
- отправляется MQTT Event `connection_lost`.

Перезапустите App, пока outage ещё активен.

Проверьте:

- тот же outage остаётся активным;
- его исходное/текущее начало месяца сохраняется;
- дублирующая outage record не создаётся.

Восстановите Интернет.

Проверьте:

- outage закрывается ровно один раз;
- duration и monthly availability обновляются;
- sensor Outages по-прежнему содержит все outages текущего месяца; ограничиваться может только число строк в dashboard presentation;
- отправляется `connection_restored`.

## 5. Presentation уведомлений

Установите ровно один local notification package.

Проверьте, что каждое поддерживаемое machine event из `event.dh_internet_app_event` активирует соответствующую ветку `trigger.id` и напрямую вызывает конечный delivery action. Оба публичных locale examples используют `persistent_notification.create`; установка может заменить только этот final action своим local delivery service.

Убедитесь, что отсутствуют вторичное событие `dh_internet_app_notification`, Notification Envelope, adapter layer и duplicated machine-schema validation. Текст уведомлений должен читать обязательные event data напрямую из `trigger.to_state.attributes`.

## 6. Опциональные bindings роутера и трафика

Сначала настройте только Router WAN/current-rate mappings.

Проверьте:

- создаются только настроенные optional MQTT entities;
- если mapped source становится unavailable, соответствующая MQTT entity также становится unavailable и исчезает из reference auto-entities card.

Затем настройте оба cumulative counters вместе.

Проверьте:

- первый sample является baseline и не считается трафиком;
- последующий рост счётчика добавляет только delta;
- totals текущего месяца растут правильно;
- Traffic history заполняется;
- restart App не дублирует usage.

Удалите один optional mapping и перезапустите App.

Проверьте, что ранее обнаруженный optional MQTT component удалён.

## 7. Телеметрия продукта

При `telemetry_enabled: false` перезапустите App и убедитесь, что heartbeat request не записывается в log и не наблюдается.

Затем явно включите `telemetry_enabled: true` и перезапустите released App. Убедитесь, что DigitalHouses Stats сразу принимает один heartbeat с product `digitalhouses_internet_app` и текущей App version. Снова перезапустите App в течение часа и убедитесь, что restart heartbeat storm не возникает. После успешного heartbeat отключите telemetry и один раз перезапустите App, затем включите её снова до наступления обычного 24-часового интервала: должен быть принят ровно один новый immediate heartbeat. Если эту немедленную попытку принудительно сделать неуспешной, перезапустите App и убедитесь, что часовой failure backoff сохраняется.

Нажмите `button.dh_internet_app_delete_telemetry` и убедитесь, что server-side installation record удалена. Если установка больше не должна отправлять данные, снова отключите telemetry.

## 8. Recovery — только после прохождения read-only тестов

Используйте заведомо исправные Home Assistant recovery entities `button.*` или `switch.*`.

Сначала проверьте `smart`:

- Internet down + Router up → только ONT;
- Internet down + Router down → только Router;
- автоматической эскалации на оба устройства нет.

Затем проверьте `both`:

- каждый цикл выполняет ONT, затем Router.

Для цели типа switch:

- подтвердите настроенный интервал power-off;
- нажмите Stop Recovery, пока switch выключен, и убедитесь, что питание восстановлено;
- повторите с обычным HAOS App Stop/Restart и убедитесь, что switch возвращён в on до выхода App.

Перезапустите App во время активного recovery incident.

Проверьте:

- Stop Recovery остаётся остановленным для того же outage;
- бюджет выполненных циклов не сбрасывается;
- активный cooldown не обходится;
- restart между циклами выдерживает retry guard до следующего power action.

## 9. Неизменяемая доставка, backup и restore

Установите или обновите текущий production App из DigitalHouses App repository.

Проверьте:

- установленная App version совпадает с текущей released version;
- production delivery использует опубликованный artifact `ghcr.io/digitalhouses/digitalhouses_internet_app:<version>`, а не локально собранный production image;
- GitHub Release фиксирует для одной версии канонический release tag, точный commit SHA, image name и image digest;
- канонический Supervisor slug остаётся `digitalhouses_internet_app`, существующие `dh_internet_app_*` entities не дублируются и не переименовываются.

Создайте Home Assistant backup, включающий App, и проверьте App backup.

Проверьте:

- присутствуют installation-specific configuration и необходимое persistent state `/data`;
- telemetry installation identity/state включены как persistent App data, если они существуют;
- backup не содержит крупную локально собранную копию воспроизводимого application image.

Восстановите этот current-production backup на поддерживаемой системе Home Assistant.

Проверьте:

- требуемый опубликованный registry image может быть получен;
- App options и persistent state `/data` восстановлены;
- telemetry installation identity и документированный runtime state переживают restore;
- App чисто запускается с теми же каноническими MQTT/device/entity identities.

Restore исторической версии или установка более старого App release поверх более нового не входит в этот общий acceptance test, если отдельная product-specific migration procedure явно этого не требует.

## 10. Соответствие runtime-контрактам

После обновления до текущего production release проверьте:

- Version равна released App version, а startup log не содержит fallback version `unknown`/local;
- сразу после restart connectivity entities не выдумывают down state до первой успешной probe observation;
- после observation Internet/Google/Cloudflare/Router показывают фактический текущий результат;
- App запускается с существующими каноническими `dh_internet_app_*` identities и не создаёт duplicate device/entities;
- persistent thresholds, outage count/history, recovery state, Recent Results и traffic totals сохраняются через restart/update;
- первый запуск новой released version может отправить один telemetry heartbeat с этой version, тогда как следующий обычный restart не создаёт heartbeat storm;
- App logs не содержат `Contract data error`, `Configuration error`, traceback или неожиданную probe failure.

Негативные случаи corruption и malformed-event покрываются автоматическими repository tests; при обычной live acceptance не повреждайте production-файлы `/data` специально для их воспроизведения.

## 11. Критерии прохождения

Проверка HAOS считается пройденной, когда:

- установка/запуск App проходят чисто;
- MQTT Discovery создаёт только канонические entities;
- connectivity, Speedtest, thresholds, Events и outage state текущего месяца работают;
- restart App корректно сохраняет outage/recovery/traffic state;
- optional mappings корректно появляются и удаляются;
- switch recovery не может оставить питание выключенным после обычного Stop/Restart;
- reference dashboard и notification package загружаются без legacy Speedtest entities;
- immutable GHCR delivery и current-production backup/restore acceptance проходят;
- runtime contract-compliance acceptance проходит без изменения канонических identities.

Историческая проверка Supervisor slug migration сохранена отдельно в `../docs/digitalhouses_internet_app/slug-migration.md`; она больше не входит в текущий runtime test path.
