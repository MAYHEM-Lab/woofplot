import util from './util'

import React, {Component} from 'react'
import {
    Button,
    Form,
    Grid,
    Header,
    Icon,
    List,
    Message,
    Modal,
    Popup,
    Segment,
    Select,
    Input,
    Table, Menu, Container, Loader
} from 'semantic-ui-react'

const DEFAULT_SYNC_HISTORY = 1500;
const CONVERSIONS = {
    'identity': {key: 'identity', value: 'identity', text: 'No conversion'},
    'f2c': {key: 'f2c', value: 'f2c', text: '°F ⭢ °C'},
    'c2f': {key: 'c2f', value: 'c2f', text: '°C ⭢ °F'},
    'kph2mph': {key: 'kph2mph', value: 'kph2mph', text: 'KPH ⭢ MPH'},
    'mph2kph': {key: 'mph2kph', value: 'mph2kph', text: 'MPH ⭢ KPH'},
    'mps2mph': {key: 'mps2mph', value: 'mps2mph', text: 'm/s ⭢ MPH'},
    'mph2mps': {key: 'mph2mps', value: 'mph2mps', text: 'MPH ⭢ m/s'},
    'mm2in': {key: 'mm2in', value: 'mm2in', text: 'mm ⭢ in'},
    'cm2in': {key: 'cm2in', value: 'cm2in', text: 'cm ⭢ in'},
    'mbar2hgby1000': {key: 'mbar2hgby1000', value: 'mbar2hgby1000', text: 'mbar ⭢ HG/1000'}
};
const NUMERICAL_PLACEHOLDERS = ['n/a']

const SOURCES_PANEL = 1
const SETTINGS_PANEL = 2

export default class Admin extends Component {

    state = {
        panel: SOURCES_PANEL,
        creating: false,
        editing: false,
        editingId: null,
        pendingDeletions: [],
        selectedUrl: null,
        peekLoading: false,
        peekUrl: "",
        peekError: null,
        peekPayload: null,
        selectedElements: [],
        clickedElement: null,
        elementLabel: null,
        elementConversion: null,
        hoveredSelected: null,
        inputName: "",
        syncClicked: false,
        syncLoading: false,
        syncHistory: DEFAULT_SYNC_HISTORY,
        syncError: null,
        syncSuccess: false,
        createLoading: false,
        createError: null,
        configLoading: false,
        configSaving: false,
        retentionEnabled: null,
        retentionWeeks: null,
        inputRetentionEnabled: null,
        inputRetentionWeeks: null
    };
    retentionInput = React.createRef();

    isUserAuthorized = () => this.props.user && this.props.user.isAdmin;

    adminPanelClosed = () => this.closeCreator();

    openCreator = (editing) => (maybeWoof) => {
        this.setState({
            creating: true,
            editing: editing,
            selectedElements: [],
            clickedElement: null,
            elementLabel: null,
            elementConversion: null,
            hoveredSelected: null,
            createLoading: false,
            createError: null
        });
        if (editing && !!maybeWoof) {
            this.setState({
                selectedUrl: maybeWoof.url,
                peekLoading: true,
                peekPayload: null,
                editingId: maybeWoof.woofId,
                peekUrl: maybeWoof.url,
                peekError: null
            });
            this.props.peekWoof(maybeWoof.url, (success, res) => {
                this.handlePeekResponse(success, res);
                const selected = [];
                maybeWoof.columns.forEach(c => {
                    selected.push({
                        name: c.name,
                        idx: c.field,
                        conversion: c.conversion === 'identity' ? null : c.conversion
                    });
                });
                this.setState({
                    selectedElements: selected,
                    inputName: maybeWoof.name
                });
            });
        } else {
            this.setState({
                selectedUrl: null,
                peekLoading: false,
                peekPayload: null,
                peekUrl: "",
                editingId: null,
                inputName: "",
                peekError: null
            });
        }
    }

    applyConfig = (result) => {
        const enabled = result !== null;
        const weeks = enabled ? (result / (7 * 24 * 60 * 60 * 1000)).toFixed(0) : null;
        this.setState({
            retentionEnabled: enabled,
            retentionWeeks: weeks,
            inputRetentionEnabled: enabled,
            inputRetentionWeeks: weeks
        });
    }

    updateConfig = () => {
        const {inputRetentionWeeks, inputRetentionEnabled} = this.state;
        this.setState({
            configSaving: true
        })
        const callback = () => {
            const refresh = (success, result) => {
                if (success) {
                    this.applyConfig(result);
                    this.setState({
                        configSaving: false
                    });
                }
            };
            this.props.loadConfig(refresh);
        }
        this.props.onUpdateConfig(inputRetentionEnabled ? inputRetentionWeeks : null, callback);
    }

    openSettingsPanel = () => {
        this.closeCreator();
        this.setState({
            panel: SETTINGS_PANEL,
            configLoading: true,
            configSaving: false,
            inputRetentionEnabled: null,
            inputRetentionWeeks: null
        });
        const callback = (success, result) => {
            if (success) {
                this.applyConfig(result);
            }
            this.setState({
                configLoading: false
            })
        }
        this.props.loadConfig(callback);
    }

    handleRetentionEnableToggle = (e, d) => {
        this.setState({inputRetentionEnabled: d.checked})
        if (!d.checked) {
            this.setState({inputRetentionWeeks: this.state.retentionWeeks});
        } else {
            setTimeout(() => this.retentionInput.current.focus(), 1);
        }
    };

    handleRetentionInput = e => {
        this.setState({inputRetentionWeeks: e.target.value})
    };

    openSourcesPanel = () => this.setState({
        panel: SOURCES_PANEL
    });

    closeCreator = () => this.setState({
        panel: SOURCES_PANEL,
        creating: false,
        editing: false
    });

    handleUrlInput = e => {
        this.setState({peekUrl: e.target.value})
    };

    handlePeekResponse = (success, res) => {
        if (this.state.peekLoading) {
            this.setState({
                peekLoading: false,
                peekPayload: success ? res : null,
                peekError: success ? null : res,
                selectedElements: [],
                clickedElement: null,
                elementLabel: null,
                elementConversion: null,
                hoveredSelected: null,
                inputName: "",
                createLoading: false,
                createError: null
            });
        }
    };

    handleSyncClicked = () => this.setState({
        syncClicked: true,
        syncSuccess: false,
        syncError: null
    });

    handleSyncClosed = () => this.setState({
        syncClicked: false,
        syncHistory: DEFAULT_SYNC_HISTORY,
        syncSuccess: false,
        syncError: null
    });

    handleHistorySet = (e) => {
        this.setState({syncHistory: e.target.value})
    };

    editWoof = (woof) => {
        this.openCreator(true)(woof);
    }

    dispatchSync = (woofId) => {
        this.setState({syncLoading: true});
        this.props.onSync(woofId, this.state.syncHistory, (success, error) => {
            this.setState({
                syncLoading: false,
                syncSuccess: success,
                syncError: success ? null : error
            });
        });
    };

    handleElementSelect = (idx) => {
        this.setState({clickedElement: idx, elementLabel: null, elementConversion: null});
    };

    handleHoverSelected = (idx, hovering) => {
        if (hovering) {
            this.setState({hoveredSelected: idx});
        } else {
            this.setState({hoveredSelected: null});
        }
    };

    handleElementAdd = (e) => {
        const {elementLabel, selectedElements, clickedElement, elementConversion} = this.state;
        e.preventDefault();
        this.setState({
            selectedElements: [...selectedElements, {
                name: elementLabel,
                idx: clickedElement,
                conversion: elementConversion
            }].sort((a, b) => a.idx - b.idx),
            clickedElement: null,
            elementLabel: null,
            elementConversion: null
        })
    };
    handleElementRemove = (idx) => this.setState({selectedElements: this.state.selectedElements.filter(e => e.idx !== idx)});

    handleElementLabelChange = (e) => this.setState({elementLabel: e.target.value});
    handleElementConversionChange = (e, v) => this.setState({elementConversion: v.value});

    handleNameChange = (e) => this.setState({inputName: e.target.value});

    handleCreate = () => {
        const {inputName, selectedUrl, selectedElements, editing, editingId} = this.state;
        this.setState({createLoading: true});

        const woof = {
            url: selectedUrl.trim(),
            name: inputName,
            columns: selectedElements.map(element => ({
                field: element.idx,
                name: element.name,
                conversion: element.conversion === null ? 'identity' : element.conversion
            }))

        };
        const callback = (success) => {
            if (success) {
                this.closeCreator();
            } else {
                this.setState({
                    createLoading: false,
                    createError: 'Failed to create source'
                });
            }
        };
        if (editing) {
            this.props.onUpdate(editingId, woof, callback);
        } else {
            this.props.onCreate(woof, callback);
        }
    };

    dispatchPeek = () => {
        this.setState({peekLoading: true, peekPayload: null, peekError: null, selectedUrl: this.state.peekUrl});
        this.props.peekWoof(this.state.peekUrl.trim(), this.handlePeekResponse);
    };

    renderPreview = () => {
        const {peekPayload, peekError, selectedElements, hoveredSelected, inputName, createLoading, createError, editing} = this.state;
        if (peekPayload != null) {
            const preview = peekPayload.typ === 'NUMERIC' ? this.renderNumPreview() : this.renderTextPreview();
            return (
                <Segment attached='top'>
                    <Header textAlign='center'>Example Response</Header>
                    <div className='preview-container'>
                        {preview}
                    </div>
                    <Grid columns={2} stackable padded relaxed='very'>
                        <Grid.Column floated='right'>
                            <Header textAlign='center' className='peek-list-header'>Selected Elements</Header>
                            <Segment basic textAlign='center' className='selected-container'>
                                {
                                    selectedElements.length === 0
                                        ?
                                        <span>No elements selected</span>
                                        :
                                        <List ordered className='peek-list'>
                                            {
                                                selectedElements.map(element =>
                                                    <List.Item key={element.idx} className='peek-list-element-wrapper'>
                                                            <span
                                                                onMouseEnter={() => this.handleHoverSelected(element.idx, true)}
                                                                onMouseLeave={() => this.handleHoverSelected(element.idx, false)}
                                                                onClick={() => this.handleElementRemove(element.idx)}
                                                                className={'peek-list-element' + (element.idx === hoveredSelected ? ' peek-list-element-over' : '')}>{element.name}
                                                            </span>
                                                        <span className={'conversion-descriptor'}>
                                                                {element.conversion == null ? null : (
                                                                    '[' + CONVERSIONS[element.conversion].text + ']'
                                                                )}
                                                            </span>
                                                    </List.Item>
                                                )}
                                        </List>
                                }
                            </Segment>
                        </Grid.Column>

                        <Grid.Column floated='right'>

                            <Form onSubmit={this.handleCreate}>
                                <Form.Input
                                    action={
                                        <Popup disabled={selectedElements.length > 0 && !!inputName}
                                               className='error-popup'
                                               on='hover'
                                               trigger={
                                                   <div className='right-action-wrapper'>
                                                       <Button
                                                           className='right-action'
                                                           content={editing ? 'Update' : 'Create'}
                                                           type='submit'
                                                           icon='signup'
                                                           loading={createLoading}
                                                           disabled={selectedElements.length === 0 || !inputName || createLoading}
                                                       />
                                                   </div>
                                               }>
                                            <Popup.Content>
                                                {selectedElements.length === 0 ? 'Select at least one element' : 'Enter source name'}
                                            </Popup.Content>

                                        </Popup>
                                    }
                                    value={inputName}
                                    className='left-input'
                                    onChange={this.handleNameChange}
                                    placeholder='Name'
                                    fluid
                                />
                            </Form>
                            {createError != null
                                ?
                                <Message negative>
                                    <Message.Header>Failed to create source</Message.Header>
                                    <p>{createError}</p>
                                </Message>
                                : null}
                        </Grid.Column>
                    </Grid>
                </Segment>
            );
        } else if (peekError != null) {
            return (
                <Message negative>
                    <Message.Header>Failed to load data</Message.Header>
                    <p>Ensure the provided source URL is valid.</p>
                </Message>
            );
        }
    };

    renderSelectedElement = (idx, entry) => {
        const {hoveredSelected} = this.state;

        return <span
            id={idx}
            onMouseEnter={() => this.handleHoverSelected(idx, true)}
            onMouseLeave={() => this.handleHoverSelected(idx, false)}
            onClick={() => this.handleElementRemove(idx)}
            className={'peek-element peek-element-selected noselect' + (idx === hoveredSelected ? ' peek-list-element-over' : '')}
            key={idx + '_elem'}
        >
            {entry}
        </span>;
    };

    renderDisabledElement = (idx, entry) =>
        <span
            id={idx}
            onMouseEnter={() => this.handleHoverSelected(idx, true)}
            onMouseLeave={() => this.handleHoverSelected(idx, false)}
            onClick={() => this.handleElementSelect(idx)}
            className={'peek-element-disabled noselect'}
            key={idx + '_elem'}>{entry}
        </span>;


    renderUnselectedElement = (idx, entry) => {
        const {clickedElement, elementLabel} = this.state;
        const curSelected = idx === clickedElement;

        return <Popup
            className='noselect'
            open={curSelected}
            onClose={() => this.handleElementSelect(null)}
            key={idx + '_popup'}
            on={'click'}
            wide='very'
            flowing
            trigger={
                <span
                    id={idx}
                    onMouseEnter={() => this.handleHoverSelected(idx, true)}
                    onMouseLeave={() => this.handleHoverSelected(idx, false)}
                    onClick={() => this.handleElementSelect(idx)}
                    className={'peek-element peek-element-unselected noselect'}
                    key={idx + '_elem'}
                >
                    {entry}
                </span>
            }
            content={
                <form onSubmit={this.handleElementAdd}>
                    <Input type='text' placeholder='Label' action>
                        <input
                            onChange={this.handleElementLabelChange}
                            autoFocus
                        />
                        <Select
                            className={'full-height-dropdown'}
                            options={Object.values(CONVERSIONS)}
                            onChange={this.handleElementConversionChange}
                            defaultValue='identity'
                        />
                        <Button
                            type='submit'
                            disabled={!elementLabel}
                        >
                            Add
                        </Button>
                    </Input>
                </form>
            }
        />
    };

    renderTextPreview = () => {
        const {selectedElements} = this.state;
        const text = this.state.peekPayload.text;
        const numColons = text.split(':').length - 1;
        const numSpaces = text.split(' ').length - 1;
        const delim = numColons > numSpaces ? ':' : ' ';

        let entries = [];
        text.split(delim).forEach(entry => {
            if (entries.length !== 0) {
                entries.push(<span className='noselect breakable' key={entries.length + '_delim'}>{delim}</span>);
            }
            const idx = entries.length / 2;
            const curAdded = selectedElements.map(a => a.idx).includes(idx);

            if (NUMERICAL_PLACEHOLDERS.includes(entry) || util.isFloat(entry)) {
                entries.push(curAdded ? this.renderSelectedElement(idx, entry) : this.renderUnselectedElement(idx, entry));
            } else {
                entries.push(this.renderDisabledElement(idx, entry));
            }
        });

        return entries
    };

    renderNumPreview = () => {
        const {selectedElements} = this.state;
        const num = this.state.peekPayload.number;
        const curAdded = selectedElements.length === 1 && selectedElements[0].idx === 0;

        return curAdded ? this.renderSelectedElement(0, num) : this.renderUnselectedElement(0, num)
    };

    renderSourceBuilder = () => {
        const {creating, editing, peekLoading, peekUrl} = this.state;
        if (creating) {
            const peekPreview = this.renderPreview();
            return (
                <Table.Row key='creator'>
                    <Table.Cell colSpan='5'>
                        <Segment className='creator-segment'>
                            <Header textAlign='center'>{editing ? "Edit Source" : "Create Source"}</Header>
                            <Grid>
                                <Grid.Row centered>
                                    <Form onSubmit={this.dispatchPeek}>
                                        <Form.Input
                                            action={
                                                <Popup
                                                    disabled={!!peekUrl}
                                                    className='error-popup'
                                                    on='hover'
                                                    trigger={
                                                        <div className='right-action-wrapper'>
                                                            <Button
                                                                className='right-action'
                                                                disabled={peekLoading || !peekUrl || editing}
                                                                loading={peekLoading}
                                                                icon
                                                                onClick={this.dispatchPeek}
                                                            >
                                                                <Icon name='search'/>
                                                            </Button>
                                                        </div>
                                                    }
                                                >
                                                    <Popup.Content>
                                                        Enter a valid URL
                                                    </Popup.Content>

                                                </Popup>
                                            }
                                            disabled={editing}
                                            value={peekUrl}
                                            className='url-input left-input'
                                            placeholder='URL'
                                            onChange={this.handleUrlInput}
                                            autoFocus
                                        />
                                    </Form>
                                </Grid.Row>
                            </Grid>
                            {peekPreview}

                        </Segment>
                    </Table.Cell>
                </Table.Row>
            )
        }
    };

    dispatchDelete = (sourceId) => {
        const pendingDeletions = this.state.pendingDeletions.slice();
        pendingDeletions.push(sourceId);
        this.setState({pendingDeletions: pendingDeletions});
        this.props.onDelete(sourceId, (success) => {
            this.setState({pendingDeletions: this.state.pendingDeletions.filter(a => a !== sourceId)});
        });
    };

    renderSourcesPanel = () => {
        const {creating, pendingDeletions, syncLoading, syncError, syncSuccess, syncHistory} = this.state;
        const woofs = this.props.woofs;
        const editRow = this.renderSourceBuilder();
        return <Table celled>
            <Table.Header>
                <Table.Row>
                    <Table.HeaderCell textAlign='center'>Name</Table.HeaderCell>
                    <Table.HeaderCell textAlign='center'>Data Types</Table.HeaderCell>
                    <Table.HeaderCell textAlign='center'>URL</Table.HeaderCell>
                    <Table.HeaderCell width='1'/>
                </Table.Row>
            </Table.Header>
            <Table.Body>
                {woofs.map(woof => {
                    return (
                        <Table.Row key={woof.woofId}>
                            <Table.Cell textAlign='center'>
                                <div>{woof.name}</div>
                            </Table.Cell>
                            <Table.Cell>
                                <List ordered>
                                    {woof.columns.map(column => (
                                        <List.Item key={woof.woofId + '_' + column.field}>
                                            {column.name}
                                            <span className={'conversion-descriptor'}>
                                                                {[null, 'identity'].includes(column.conversion) ? null : (
                                                                    '[' + CONVERSIONS[column.conversion].text + ']'
                                                                )}
                                                            </span>
                                        </List.Item>
                                    ))}
                                </List>
                            </Table.Cell>
                            <Table.Cell textAlign='center'>
                                <div><code>{woof.url}</code></div>
                            </Table.Cell>
                            <Table.Cell textAlign='center' className='action-cell'>

                                <Popup
                                    className='noselect'
                                    // open={syncClicked}
                                    key={woof.woofId}
                                    position='top center'
                                    onClose={() => this.handleSyncClosed()}
                                    on={'click'}
                                    trigger={
                                        <Button
                                            loading={syncLoading}
                                            disabled={!this.isUserAuthorized() || syncLoading}
                                            icon
                                            onClick={() => this.handleSyncClicked()}
                                            className='source-action-button'
                                        >
                                            <Icon name='redo alternate'/>
                                        </Button>

                                    }
                                    content={
                                        <div>
                                            <Form onSubmit={() => this.dispatchSync(woof.woofId)}>
                                                <Form.Field>
                                                    <label>How many recent events to load:</label>
                                                    <Form.Input
                                                        action={{
                                                            content: 'Load',
                                                            disabled: syncLoading || !syncHistory || !util.isInt(syncHistory),
                                                            loading: syncLoading
                                                        }}
                                                        disabled={syncLoading}

                                                        onChange={this.handleHistorySet}
                                                        placeholder='History'
                                                        defaultValue={DEFAULT_SYNC_HISTORY}
                                                        autoFocus
                                                    />
                                                </Form.Field>

                                            </Form>
                                            {syncError != null ?
                                                <Message negative>
                                                    <p>{syncError}</p>
                                                </Message>
                                                : (syncSuccess ?
                                                        <Message positive>
                                                            <p>Recent history loaded</p>
                                                        </Message>
                                                        : null
                                                )}
                                        </div>
                                    }
                                />
                                <Button
                                    loading={pendingDeletions.includes(woof.woofId)}
                                    disabled={!this.isUserAuthorized() || pendingDeletions.includes(woof.woofId)}
                                    icon
                                    onClick={() => this.editWoof(woof)}
                                    className='source-action-button'
                                >
                                    <Icon name='edit'/>
                                </Button>
                                <Button
                                    loading={pendingDeletions.includes(woof.woofId)}
                                    disabled={!this.isUserAuthorized() || pendingDeletions.includes(woof.woofId)}
                                    icon
                                    negative
                                    onClick={() => this.dispatchDelete(woof.woofId)}
                                    className='source-action-button'
                                >
                                    <Icon name='trash alternate'/>
                                </Button>
                            </Table.Cell>
                        </Table.Row>
                    );
                })}

                {editRow}

            </Table.Body>
            <Table.Footer fullWidth>
                <Table.Row>
                    <Table.HeaderCell colSpan='6'>
                        {
                            creating ?
                                <Button
                                    floated='right'
                                    icon
                                    labelPosition='left'
                                    primary
                                    size='small'
                                    onClick={this.closeCreator}
                                >
                                    <Icon name='times'/> Cancel
                                </Button>
                                :
                                <Button
                                    floated='right'
                                    icon
                                    disabled={!this.isUserAuthorized()}
                                    labelPosition='left'
                                    primary
                                    size='small'
                                    onClick={this.openCreator(false)}
                                >
                                    <Icon name='plus'/> Add Source
                                </Button>}
                        {this.isUserAuthorized() ? null :
                            <Message className='unauthorized-message message-right' floating size='mini' compact attached='bottom' warning content="Sign in to edit sources"/>
                        }
                    </Table.HeaderCell>
                </Table.Row>
            </Table.Footer>
        </Table>
    }

    renderSettingsPanel = () => {
        const {retentionWeeks, retentionEnabled, inputRetentionWeeks, inputRetentionEnabled, configLoading, configSaving} = this.state;
        const dispRetentionChecked = inputRetentionEnabled;
        const dispRetentionWeeks =  inputRetentionWeeks === null ? '' : inputRetentionWeeks;
        const validWeeks = !inputRetentionEnabled || dispRetentionWeeks === '' || util.isInt(inputRetentionWeeks);
        const authorized = this.isUserAuthorized();
        const canSubmit = authorized &&
            (inputRetentionEnabled !== null && (!inputRetentionEnabled || util.isInt(inputRetentionWeeks))) &&
            (inputRetentionWeeks !== retentionWeeks || inputRetentionEnabled !== retentionEnabled);

        if (configLoading) {
            return <Loader className='settings-loader' size='large' inline='centered'/>;
        } else {
            return <Container>
                <Header as='h3' className='setting-name' content='Retention Policy'/>
                <Form onSubmit={() => {
                    if (canSubmit) this.updateConfig()
                }}>
                    <Form.Checkbox onChange={this.handleRetentionEnableToggle} checked={dispRetentionChecked} label='Enable automatic data pruning'/>
                    <Form.Field inline error={!validWeeks}>
                        <Input ref={this.retentionInput} disabled={!dispRetentionChecked} onChange={this.handleRetentionInput} value={dispRetentionWeeks} placeholder='Retention' label={{basic: true, content: 'weeks'}} labelPosition='right'/>
                    </Form.Field>
                </Form>
                <span className='setting-description'>Controls how long data will be retained. If enabled, data older than configured will be automatically deleted.</span>
                <Button
                    className='message-left'
                    loading={configSaving}
                    positive={authorized}
                    onClick={this.updateConfig}
                    disabled={!canSubmit}
                    content='Update settings'
                />
                {this.isUserAuthorized() ? null :
                    <Message floating size='mini' className='unauthorized-message message-left' compact attached='bottom' warning content="Sign in to modify settings"/>
                }
            </Container>
        }
    }

    render() {
        const {panel} = this.state;
        return (
            <Modal
                dimmer='inverted'
                onClose={this.adminPanelClosed}
                centered={false}
                size='large'
                trigger={<Button size='small' icon><Icon name='setting'/></Button>}>
                <Modal.Header>Manage</Modal.Header>
                <Modal.Content>
                    <Menu pointing secondary>
                        <Menu.Item name='sources' active={panel === SOURCES_PANEL} onClick={this.openSourcesPanel}/>
                        <Menu.Item name='settings' active={panel === SETTINGS_PANEL} onClick={this.openSettingsPanel}/>
                    </Menu>
                    {panel === SOURCES_PANEL ? this.renderSourcesPanel() : this.renderSettingsPanel()}
                </Modal.Content>
            </Modal>
        );
    }
}
