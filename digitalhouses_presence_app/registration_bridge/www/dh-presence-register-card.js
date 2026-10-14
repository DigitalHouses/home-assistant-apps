/* DH Presence: authenticated one-time phone registration.
 * Install as a Home Assistant dashboard JS module resource (/local/...).
 * This card never asks for user IDs, IP addresses or MAC addresses.
 * It sends only a selected HA Mobile Companion config-entry/tracker pair.
 */
class DHPresenceRegisterCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this._loaded = false;
    this._busy = false;
    this._choices = [];
    this._status = '';
    this._error = false;
    this.shadowRoot.innerHTML = `
      <ha-card header="Регистрация телефона · DH Presence">
        <div style="padding:0 16px 16px">
          <p style="margin:0 0 12px">Откройте эту карточку непосредственно
          на телефоне через локальный адрес Home Assistant (не Cloudflare,
          VPN или удалённый браузер). Выберите именно этот телефон.</p>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <select id="devices" style="flex:1;min-width:190px;padding:10px"></select>
            <mwc-button id="reload" outlined>Обновить список</mwc-button>
            <mwc-button id="register" raised>Зарегистрировать</mwc-button>
          </div>
          <div id="info" role="status" style="padding-top:12px"></div>
        </div>
      </ha-card>`;
    this.shadowRoot.getElementById('reload').addEventListener('click', () => this.load());
    this.shadowRoot.getElementById('register').addEventListener('click', () => this.register());
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded && !this._busy) {
      this._loaded = true;
      this.load();
    }
  }

  setConfig(config) { this._config = config; }

  getCardSize() { return 3; }

  show(message, error = false) {
    const node = this.shadowRoot.getElementById('info');
    node.textContent = String(message);
    node.style.color = error ? 'var(--error-color)' : 'var(--primary-text-color)';
  }

  async load() {
    if (!this._hass || this._busy) return;
    this._busy = true;
    const select = this.shadowRoot.getElementById('devices');
    this.show('Чтение устройств из Home Assistant…');
    try {
      const entries = await this._hass.connection.sendMessagePromise({
        type: 'dh_presence/candidates',
      });
      this._choices = Array.isArray(entries) ? entries : [];
      select.replaceChildren();
      for (const item of this._choices) {
        const option = document.createElement('option');
        option.value = String(this._choices.indexOf(item));
        option.textContent = item.device_name + ' · ' + item.tracker;
        select.appendChild(option);
      }
      this.show(this._choices.length
        ? 'Устройства получены из вашей учётной записи HA. Выберите телефон, с которого открыта карточка.'
        : 'У этой учётной записи нет зарегистрированных GPS-трекеров Mobile Companion.');
    } catch (error) {
      this.show('Адаптер WebSocket не готов: ' + (error.message || String(error)), true);
    } finally { this._busy = false; }
  }

  async register() {
    if (!this._hass || this._busy) return;
    const index = Number(this.shadowRoot.getElementById('devices').value);
    const choice = this._choices[index];
    if (!choice) return this.show('Сначала выберите устройство.', true);
    if (!window.confirm('Вы открыли Home Assistant именно на устройстве «'
        + choice.device_name + '» через домашнюю Wi-Fi сеть?')) return;
    this._busy = true;
    try {
      const result = await this._hass.connection.sendMessagePromise({
        type: 'dh_presence/register',
        entry_id: choice.entry_id,
        tracker: choice.tracker,
      });
      this.show('Запрос для «' + result.device_name
        + '» принят. DH Presence проверяет настоящий IP/MAC через ARP. '
        + 'Это не означает, что телефон уже зарегистрирован. '
        + 'Нажмите «Обновить список» либо проверьте статус после нескольких секунд.');
    } catch (error) {
      this.show('Регистрация отклонена: ' + (error.message || String(error)), true);
    } finally { this._busy = false; }
  }
}
if (!customElements.get('dh-presence-register-card')) {
  customElements.define('dh-presence-register-card', DHPresenceRegisterCard);
}
