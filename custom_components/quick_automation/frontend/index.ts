import { css, html, LitElement } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';

const tabs = [
    {
        path: "/quick_automation",
        name: "Quick Automations",
    }
];

@customElement("quick-automation-panel")
export class QuickAutomationPanel extends LitElement {

    @property()
    hass: any

    @property()
    narrow: boolean

    @property()
    route: object

    @property()
    panel: object

    @state()
    private _items: object[] | undefined = undefined;

    @state()
    private _editor: EntryRecord | undefined = undefined;

    _columns(narrow: boolean) {
        const columns: any = {
            entry_id: {
                hidden: true,
            },
            enabled: {
                title: "",
                type: "icon",
                template: (enabled: boolean, row: EntryRecord) => {
                    const _handleChange = (event: any) => {
                        this._toggle(row);
                    };
                    return html`
                    <ha-switch
                        .checked=${enabled}
                        @change=${_handleChange}
                    ></ha-switch>            
                    `;
                }
            },
            icon: {
                title: "",
                type: "icon",
                template: (icon: string) => html`<ha-icon slot="item-icon" icon="mdi:link-variant"></ha-icon>`,
            },
            title: {
                title: "Name",
                sortable: true,
                filterable: true,
                direction: "asc",
                width: narrow? undefined: "500px",
                grows: narrow? true: false,
                template: (value: string) => html`${value}`,
            },
        };
        if (!narrow) {
            columns["info"] = {
                title: "Details",
                sortable: false,
                filterable: false,
                direction: "asc",
                grows: true,
                template: (value: any, row: EntryRecord) => {
                    const details = row.links
                        .filter((item) => item.enabled)
                        .map((item) => configBlocks[item.type].title + (item.reverse? ' (Reversed)': ''))
                        .join(', ')
                    return html`${details}`;
                }
            };
        }
        columns["edit"] = {
            title: "",
            filterable: false,
            grows: false,
            template: (value: string, row: EntryRecord) => {
                const _action = () => {
                    this._edit(row)
                };
                return html`
                    <mwc-button
                        @click=${_action}
                    >
                        Edit
                    </mwc-button>
                `;
            }
        };
        columns["remove"] = {
            title: "",
            filterable: false,
            grows: false,
            template: (value: string, row: EntryRecord) => {
                const _action = () => {
                    this._remove(row)
                };
                return html`
                    <mwc-button
                        @click=${_action}
                    >
                        Remove
                    </mwc-button>
                `;
            }
        };
        return columns;
    }

    async _remove(row: EntryRecord) {
        await this.hass.connection.sendMessagePromise({
            type: 'quick_automation/remove_entry',
            entry_id: row.entry_id,
        });
        this._load();
    }

    async _toggle(row: EntryRecord) {
        await this.hass.connection.sendMessagePromise({
            type: 'quick_automation/toggle_enabled',
            entry_id: row.entry_id,
            enabled: !row.enabled,
        });
        this._load();
    }

    async _load() {
        const resp = await this.hass.connection.sendMessagePromise({
            type: 'quick_automation/list',
        });
        console.log('_load:', resp);
        this._items = resp;
    }

    _getItems(): object[] {
        if (this._items) {
            return this._items;
        }
        this._load();
        return [];
    }

    _edit(row: EntryRecord) {
        console.log("_edit:", row);
        if (row) {
            this._editor = row;
        }
    }

    _add() {
        this._editor = {
            entry_id: undefined,
            title: '',
            enabled: true,
            source: {
                entity_id: undefined,
                device_id: undefined,
            },
            destination: {
                entity_id: undefined,
                device_id: undefined,
            },
            links: [],
        }
    }

    async _save(event: any) {
        const entry = event.detail;
        console.log("On save:", entry);
        await this.hass.connection.sendMessagePromise({
            type: 'quick_automation/update_entry',
            ...entry,
        });
        this._load();
    }

    render() {
        // console.log("Panel: ", this.hass, this._editorParams);
        return html`
        <hass-tabs-subpage-data-table
            .hass=${this.hass}
            .narrow=${this.narrow}
            back-path="/config"
            .route=${this.route}
            .tabs=${tabs}
            .columns=${this._columns(this.narrow)}
            .data=${this._getItems()}
            id="entry_id"
            hasFab
        >
            <ha-fab
                slot="fab"
                label="Add new"
                extended
                @click=${() => this._add()}
            >
            </ha-fab>
        </hass-tabs-subpage-data-table>
        <quick-automation-editor
            .data=${this._editor}
            .hass=${this.hass}
            @save=${this._save}
            @close=${() => {
                this._editor = undefined;
            }}
        >
        </quick-automation-editor>
        `;
    }
}

type DeviceEntity = {
    entity_id?: string;
    device_id?: string;
    area_id?: string;
};

type Link = {
    type: string;
    enabled: boolean;
    reverse: boolean | undefined;
    extra: any | undefined;
    triggers: string[];
    trigger: string | undefined;
};

type EntryRecord = {
    entry_id: string | undefined;
    title: string;
    enabled: boolean;
    source: DeviceEntity;
    destination: DeviceEntity;
    links: Link[];
};

const configBlocks: {
    [id: string]: {
        title: string;
        reverse: boolean;
        select_title?: string;
    }
} = {
    on_off: {
        title: "ON/OFF",
        reverse: true
    },
    brightness: {
        title: "Brightness",
        reverse: true
    },
    left_right: {
        title: "Color temperature",
        reverse: true,
    },
    toggle: {
        title: "Toggle",
        reverse: false,
        select_title: "Action"
    },
};

@customElement("quick-automation-editor")
export class SuperGroupsEditor extends LitElement {

    @property()
    data: EntryRecord | undefined = undefined;

    @property()
    hass: any

    protected willUpdate(props: Map<string, unknown>): void {
        if (props.has("data") && this.data) {
            this._data = { // Copy
                ...this.data
            };
        }
    }

    @state()
    _data: EntryRecord | undefined = undefined;

    _cancel() {
        this._data = undefined;
        this.dispatchEvent(new CustomEvent('close', {
            bubbles: false
        }));
    }

    _save() {
        this.dispatchEvent(new CustomEvent('save', {
            detail: {
                ...this._data,
            }, 
            bubbles: false
        }));
        this._cancel();
    }

    _titleChanged(event: any) {
        this._data = {
            ...this._data,
            title: event.detail.value,
        };
    }

    @property()
    _sourceSelector : {} = {
        target: {},
    };

    @property()
    _destinationSelector : {} = {
        target: {},
    };

    targetSet(target: DeviceEntity) {
        return target.entity_id || target.device_id? true: false;
    }

    async _updateTarget(value: DeviceEntity | undefined, name: string) {
        const oneItem = (value: any) => Array.isArray(value)? value[value.length-1]: value;
        this._data = {
            ...this._data,
            [name]: {
            },
        };    
        if (value && value.device_id) {
            this._data = {
                ...this._data,
                [name]: {
                    device_id: oneItem(value.device_id),
                },
            };    
        }
        if (value && value.entity_id) {
            this._data = {
                ...this._data,
                [name]: {
                    entity_id: oneItem(value.entity_id),
                },
            };    
        }
        if (this.targetSet(this._data.source) && this.targetSet(this._data.destination)) {
            await this._loadTriggerActions();
        }
    }

    _onSourceChanged(event: any) {
        const value = event.detail.value as DeviceEntity;
        this._updateTarget(value, 'source');
    };

    _onDestinationChanged(event: any) {
        const value = event.detail.value as DeviceEntity;
        this._updateTarget(value, 'destination');
    };

    async _loadTriggerActions() {
        const resp = await this.hass.connection.sendMessagePromise({
            type: "quick_automation/load_trigger_action",
            source: this._data.source,
            destination: this._data.destination,
        });
        console.log('_loadTriggerActions', resp);
        this._data = {
            ...this._data,
            title: resp.title,
            links: resp.links,
        };
    }

    _renderLink(index: number, link: Link) {
        const onEnabled = (event: any) => {
            link.enabled = event.detail.value;
            this._data = {
                ...this._data,
                links: [...this._data.links],
            };
        };
        const onReversed = (event: any) => {
            link.reverse = event.detail.value;
            this._data = {
                ...this._data,
                links: [...this._data.links],
            };
        };
        const onExtra = (event: any) => {
            link.extra = event.detail.value;
            this._data = {
                ...this._data,
                links: [...this._data.links],
            };
        };
        const onSelect = (event: any) => {
            console.log("Selected:", event.detail);
            link.trigger = event.detail.value;
            this._data = {
                ...this._data,
                links: [...this._data.links],
            };
        }
        const config = configBlocks[link.type];
        let selectorHtml = undefined;
        if (link.triggers.length) {
            const selector = {
                select: {
                    options: link.triggers,
                }
            };
            selectorHtml = html`
            <ha-selector
                label="${config.select_title}"
                .hass=${this.hass}
                .selector=${selector}
                .value=${link.trigger}
                @value-changed=${onSelect}
            >
            </ha-selector-target>
            `;
        }
        let subPart = html``;
        if (link.enabled) {
            let reversedHtml = html``;
            if (config.reverse) {
                reversedHtml = html`
                    <ha-selector-boolean
                        label="Reversed"
                        .disabled=${!config.reverse}
                        .hass=${this.hass}
                        .value=${link.reverse}
                        @value-changed=${onReversed}
                    >
                    </ha-selector-boolean>
                `;
            }
            subPart = html`
                ${reversedHtml}
                ${selectorHtml}
                <label>Extra service data:</label>
                <ha-code-editor
                    .hass=${this.hass}
                    .value=${link.extra}
                    mode="yaml"
                    label="Extra service data"
                    @value-changed=${onExtra}
                >
                </ha-code-editor>
            `;
        }
        return html`
            <p>${config.title}</p>
            <ha-selector-boolean
                label="Enabled"
                .hass=${this.hass}
                .value=${link.enabled}
                @value-changed=${onEnabled}
            >
            </ha-selector-boolean>
            ${subPart}
        `;
    }


    protected render() {
        if (!this._data) return html``;
        const allSet = this._data.title.trim() 
                && this._data.links.length 
                && this.targetSet(this._data.source) 
                && this.targetSet(this._data.destination);
        const titleRow = html`
            <paper-input
                .value=${this._data.title}
                @value-changed=${this._titleChanged}
                label="Name"
            >
            </paper-input>
        `;
        const header = html`
            <span class="header_title">Entry Editor</span>
        `;
        return html`
        <ha-dialog 
            scrimClickAction
            escapeKeyAction
            .heading=${header}
            open
        >
            <div>
                <div class="form">
                    <div>
                        ${titleRow}
                    </div>
                    <div>
                        <p>Source:</p>
                        <ha-selector
                            label="Source"
                            .hass=${this.hass}
                            .selector=${this._sourceSelector}
                            .value=${this._data.source}
                            @value-changed=${this._onSourceChanged}
                        >
                        </ha-selector-target>
                    </div>
                    <div>
                        <p>Destination:</p>
                        <ha-selector
                            label="Source"
                            .hass=${this.hass}
                            .selector=${this._destinationSelector}
                            .value=${this._data.destination}
                            @value-changed=${this._onDestinationChanged}
                        >
                        </ha-selector-target>
                    </div>
                    ${this._data.links.map((link, index) => this._renderLink(index, link))}
                </div>
            </div>
            <mwc-button
                @click=${this._save}
                slot="primaryAction"
                .disabled=${!allSet}
            >
                Save
            </mwc-button>
            <mwc-button
                @click=${this._cancel}
                slot="secondaryAction"
            >
                Cancel
            </mwc-button>
        </ha-dialog>
        `;
    }

    static get styles() {
        return css`
            ha-dialog {
                --mdc-dialog-heading-ink-color: var(--primary-text-color);
                --mdc-dialog-content-ink-color: var(--primary-text-color);
                --justify-action-buttons: space-between;
            }                    
            p {
                font-size: 1.3rem;
                margin: 1em 0;
            }
            label {
                margin: 0.5em 0;
            }
        `;
    }
}