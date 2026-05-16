import util from './util'
import _ from 'lodash';

import React, {Component} from 'react';
import {Button, Checkbox, Dropdown, Form, Grid, Header, Icon, Input, Label, Loader, Message, Modal, Popup} from 'semantic-ui-react';
import {Line} from 'react-chartjs-2';

import Admin from './Admin.js'

import 'chartjs-plugin-colorschemes';
import './style.css';
import RangePicker from "./RangePicker";

const api = '/api/';
const REFRESH_MS = 30_000;

export default class App extends Component {
    chartRef = React.createRef();

    selectedSettings = {
        columnsLeft: [],
        columnsRight: [],
        rawElements: '',
        autoElements: true,
        relativeRange: null,
        absoluteRange: null
    };

    state = {
        userLoading: true,
        user: null,
        loginOpen: false,
        loginFailed: false,
        loginLoading: false,
        username: null,
        password: null,
        userDropdownOpen: false,

        changePasswordOpen: false,
        changePasswordFailed: false,
        changePasswordLoading: false,
        newPassword: null,
        newPasswordValidate: null,

        prePlotError: null,
        isFetching: false,
        isLoading: false,
        loadedWoofs: [],
        loadedColumns: [],
        selectedSettings: this.selectedSettings,
        plottedSettings: null,
        displayedSettings: null,
        datasets: []
    };
    leftAxisRef = React.createRef();
    rightAxisRef = React.createRef();

    limitInputRef = React.createRef();
    plotButton = React.createRef();

    handleErrors = (response) => {
        if (!response.ok) throw new Error(response.statusText);
        return response;
    };

    componentWillUnmount = () => {
        clearInterval(this.interval);
    };

    componentDidMount = () => {
        this.interval = setInterval(() => {
            this.loadData(true);
            this.fetchWoofs(true);
        }, REFRESH_MS);

        this.fetchUser();

        const chartContainer = document.getElementById('chart-wrapper');
        const dataCanvas = document.getElementById('data-chart');
        const cursorCanvas = document.getElementById('cursor');
        const cursorCtx = cursorCanvas.getContext('2d');

        chartContainer.onmousemove = (e) => {
            const chartArea = this.chartRef.current.chartInstance.chartArea;
            const dataWidth = parseInt(dataCanvas.style.width, 10);
            const dataHeight = parseInt(dataCanvas.style.height, 10);
            cursorCanvas.width = dataWidth;
            cursorCanvas.height = dataHeight;
            const {offsetLeft, offsetTop} = cursorCanvas;
            const {clientX, clientY} = e;
            cursorCtx.clearRect(0, 0, cursorCanvas.width, cursorCanvas.height);
            if (clientX <= offsetLeft + dataWidth && clientX >= 48 && clientY <= offsetTop + dataHeight && clientY >= offsetTop) {
                cursorCtx.beginPath();
                cursorCtx.moveTo(clientX - offsetLeft, chartArea.top);
                cursorCtx.lineTo(clientX - offsetLeft, chartArea.bottom);
                cursorCtx.stroke();
            }
        };
        chartContainer.onmouseleave = () => {
            cursorCtx.clearRect(0, 0, cursorCanvas.width, cursorCanvas.height);
        };

        this.fetchWoofs(false);
    };

    fetchUser = () => {
        fetch(`${api}user`)
            .then(this.handleErrors)
            .then(response => response.json())
            .then(result => {
                this.setState({
                    user: result
                })
            })
            .catch(() => {
            })
            .finally(() => {
                this.setState({
                    userLoading: false
                })
            });
    }

    createWoof = (woof, callback) => {
        fetch(`${api}woof`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(woof)
        })
            .then(this.handleErrors)
            .then(() => this.fetchWoofs(true).then(() => callback(true)))
            .catch(() => this.fetchWoofs(true).then(() => callback(false)));
    };

    updateWoof = (woofId, woof, callback) => {
        fetch(`${api}woof/${woofId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(woof)
        })
            .then(this.handleErrors)
            .then(() => this.fetchWoofs(true))
            .then(() => callback(true))
            .then(() => this.loadData(true))
            .catch(() => this.fetchWoofs(true).then(() => callback(false)));
    };

    deleteWoof = (woofId, callback) =>
        fetch(`${api}woof/${woofId}`, {
            method: 'DELETE'
        })
            .then(this.handleErrors)
            .then(() => this.fetchWoofs(true).then(() => callback(true)))
            .catch(() => this.fetchWoofs(true).then(() => callback(false)));

    peekWoof = (woofUrl, callback) =>
        fetch(`${api}peek/${encodeURIComponent(woofUrl)}`)
            .then(this.handleErrors)
            .then(response => response.json())
            .then(result => callback(true, result))
            .catch((e) => callback(false, e.message));

    syncWoof = (woofId, history, callback) =>
        fetch(`${api}sync/${woofId}?history=${history}`, {
            method: 'POST'
        })
            .then(this.handleErrors)
            .then(result => callback(true, null))
            .catch((e) => callback(false, e.message));

    updateConfig = (retentionWeeks, callback) => {
        const req = !!retentionWeeks
            ?
            fetch(`${api}retention/${retentionWeeks}`, {method: 'POST'})
            :
            fetch(`${api}retention`, {method: 'DELETE'});
        req.then(this.handleErrors)
            .then(result => callback(true, null))
            .catch((e) => callback(false, e.message));
    }

    loadConfig = (callback) => {
        fetch(`${api}retention`)
            .then(this.handleErrors)
            .then(response => response.json())
            .then(result => callback(true, result))
            .catch((e) => callback(false, e.message));
    }

    fetchWoofs = (background) => {

        if (!background) {
            this.setState({isFetching: true});
        }
        return fetch(`${api}woof`)
            .then(this.handleErrors)
            .then(response => response.json())
            .then(results => {
                const loaded = results.flatMap(woof =>
                    woof.columns.map(column => {
                        const id = woof.woofId + ':' + column.field;
                        const name = column.name;
                        const woofName = woof.name;
                        return {
                            [id]: {
                                key: id,
                                woofId: woof.woofId,
                                woofName: woofName,
                                field: column.field,
                                name: name,
                                conversion: column.conversion,
                                item: {
                                    selected: false,
                                    text: name,
                                    fullname: '[' + woofName + '] ' + name,
                                    label: woofName,
                                    value: id,
                                }
                            }
                        }
                    })
                );
                const columns = Object.assign({}, ...loaded);
                const {selectedSettings, plottedSettings} = this.state;

                const selectedLeft = selectedSettings.columnsLeft.filter(column => column in columns);
                const selectedRight = selectedSettings.columnsRight.filter(column => column in columns);

                let currentPlotted = plottedSettings;
                if (currentPlotted !== null) {
                    const plottedLeft = currentPlotted.columnsLeft.filter(column => column in columns);
                    const plottedRight = currentPlotted.columnsRight.filter(column => column in columns);
                    currentPlotted = {...currentPlotted, columnsLeft: plottedLeft, columnsRight: plottedRight}
                }

                this.leftAxisRef.current.setState({value: selectedLeft});
                this.rightAxisRef.current.setState({value: selectedRight});

                this.setState({
                    loadedWoofs: results,
                    loadedColumns: columns,
                    selectedSettings: {...selectedSettings, columnsLeft: selectedLeft, columnsRight: selectedRight},
                    plottedSettings: currentPlotted
                });
                if (!background) {
                    this.setState({isFetching: false});
                }
            })
            .catch((reason) => {
                console.log(reason);
                if (!background) {
                    this.setState({isFetching: false});
                }
            });
    };

    handlePlot = () => this.setState({plottedSettings: this.state.selectedSettings}, () => this.loadData(false));

    loadData = (background) => {
        const {plottedSettings, loadedColumns, prePlotError} = this.state;

        if (plottedSettings) {
            const {columnsLeft, columnsRight, relativeRange, absoluteRange, autoElements, rawElements} = plottedSettings;

            if (prePlotError == null) {
                let timeRange;
                let rawParam;
                let queryInterval;

                if (relativeRange) {
                    const retentionMinutes = relativeRange.value;
                    timeRange = (retentionMinutes === -1 && rawElements) ?
                        '' :
                        `&from=${Date.now() - (retentionMinutes === -1 ? 60 : retentionMinutes) * 60 * 1000}&to=${Date.now()}`;
                    queryInterval = autoElements ? (retentionMinutes === -1 ? 'minute' : relativeRange.interval) : 'moment';
                } else {
                    const {start, end, interval} = absoluteRange;
                    timeRange = `&from=${start.getTime()}&to=${end.getTime()}`
                    queryInterval = autoElements ? interval : 'moment';
                }

                rawParam = rawElements ? `&raw_elements=${rawElements}` : '';
                if (!background) {
                    this.setState({isLoading: true, hasPlotted: true});
                }
                const agg = autoElements ? 'average' : 'raw';
                Promise
                    .all(columnsLeft.concat(columnsRight).map(id => {
                        const column = loadedColumns[id];
                        return fetch(`${api}query?woofId=${column.woofId}&field=${column.field}${timeRange}&aggregation=${agg}&interval=${queryInterval}${rawParam}`)
                            .then(this.handleErrors)
                            .then(response => response.json())
                            .then(results => {

                                return {
                                    label: column.item.fullname,
                                    yAxisID: columnsRight.includes(column.key) ? 'y-axis-r' : 'y-axis-l',
                                    fill: false,
                                    borderJoinStyle: 'round',
                                    lineTension: 0,
                                    pointRadius: 3,
                                    pointHoverRadius: 6,
                                    data: results.map(metric => {
                                        return {
                                            x: metric.timestamp,
                                            y: metric.value
                                        };
                                    })
                                };
                            })
                    }))
                    .then(results => {
                        if (!background || _.isEqual(this.state.plottedSettings, plottedSettings)) {
                            this.setState({
                                datasets: results,
                                displayedSettings: plottedSettings
                            });
                        }
                    })
                    .catch((reason) => {
                        console.log(reason);
                    })
                    .finally(() => {
                        if (!background) {
                            this.setState({isLoading: false});
                        }
                    });
            }
        }
    };

    handleAutoElementToggle = (event, data) => {
        if (!data.checked) {
            this.setState({selectedSettings: {...this.state.selectedSettings, autoElements: false}});
            setTimeout(() => {
                this.limitInputRef.current.focus();
            }, 0)
        } else {
            this.setState({selectedSettings: {...this.state.selectedSettings, rawElements: '', autoElements: true}});
        }
    };

    handleElementInput = (event, data) => {
        this.setState({selectedSettings: {...this.state.selectedSettings, rawElements: event.target.value}});
    };

    selectRelativeRange = (relativeRange) => {
        this.setState({selectedSettings: {...this.state.selectedSettings, relativeRange: relativeRange, absoluteRange: null}})
    }

    selectAbsoluteRange = (absoluteRange) => {
        this.setState({selectedSettings: {...this.state.selectedSettings, relativeRange: null, absoluteRange: absoluteRange}})
    }

    handleLeftColumnSelect = (event, data) => {
        this.setState({selectedSettings: {...this.state.selectedSettings, columnsLeft: data.value}});
    };

    handleRightColumnSelect = (event, data) => {
        this.setState({selectedSettings: {...this.state.selectedSettings, columnsRight: data.value}});
    };

    isPlottable = () => {
        const {selectedSettings} = this.state;
        return (selectedSettings.autoElements || (selectedSettings.rawElements && util.isInt(selectedSettings.rawElements)));
    };

    setCredentials = (e, {name, value}) => {
        this.setState({[name]: value});
    }

    submitLogout = () => {
        this.setState({userLoading: true});
        fetch(`${api}logout`, {
            method: 'POST'
        })
            .then(this.handleErrors)
            .then(() => this.setState({user: null, userDropdownOpen: false}))
            .finally(() => this.setState({userLoading: false}));
    }

    newPasswordValid = () => {
        const {newPassword, newPasswordValidate} = this.state;
        return newPassword && newPasswordValidate && newPassword === newPasswordValidate;
    }

    changePassword = () => {
        const {user, newPassword} = this.state;
        this.setState({changePasswordLoading: true});
        fetch(`${api}changepassword`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({
                username: user.username,
                password: newPassword
            })
        })
            .then(this.handleErrors)
            .then(() => this.setState({changePasswordOpen: false, changePasswordFailed: false, newPassword: null, newPasswordValidate: null}))
            .catch(() => this.setState({changePasswordFailed: true}))
            .finally(() => this.setState({changePasswordLoading: false}));
    }

    submitLogin = () => {
        const {username, password} = this.state;
        this.setState({loginLoading: true});
        fetch(`${api}login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({
                username: username,
                password: password
            })
        })
            .then(this.handleErrors)
            .then(response => response.json())
            .then((result) => this.setState({user: result, loginOpen: false, loginFailed: false}))
            .catch(() => this.setState({loginFailed: true}))
            .finally(() => this.setState({loginLoading: false}));
    };

    render() {
        const {
            selectedSettings, displayedSettings,
            isFetching, isLoading,
            loadedColumns, loadedWoofs,
            datasets, prePlotError,
            loginFailed, loginOpen, username, password, loginLoading, user, userLoading, userDropdownOpen,
            changePasswordOpen, changePasswordFailed, changePasswordLoading, newPasswordValidate
        } = this.state;
        const {relativeRange, absoluteRange, columnsLeft, columnsRight, autoElements} = displayedSettings || {};

        let minDate;
        let maxDate;
        let rangeUnit;
        let format;
        if (relativeRange) {
            if (relativeRange.value === -1 && !autoElements) {
                minDate = null;
            } else {
                minDate = Date.now() - (relativeRange.value === -1 ? 60 : relativeRange.value) * 60 * 1000;
            }
            maxDate = Date.now();
            rangeUnit = relativeRange.unit;
            format = relativeRange.format;
        } else if (absoluteRange) {
            minDate = absoluteRange.start;
            maxDate = absoluteRange.end;
            rangeUnit = absoluteRange.unit;
            format = absoluteRange.format;
        }

        const minPoint = Math.min(datasets.map(set => set.data ? set.data.length > 0 ? set.data[0].x ? set.data[0].x : 0 : 0 : 0))
        const maxPoint = Math.max(datasets.map(set => set.data ? set.data.length > 0 ? set.data[set.data.length - 1].x ? set.data[set.data.length - 1].x : 0 : 0 : 0))
        const maxDataWidth = maxPoint - minPoint;

        const unit = rangeUnit
            ? rangeUnit
            : maxDataWidth >= 1.5 * 30 * 24 * 60 * 60 * 1000 ? 'month'
                : maxDataWidth >= 10 * 24 * 60 * 60 * 1000 ? 'week'
                    : maxDataWidth >= 24 * 60 * 60 * 1000 ? 'day'
                        : maxDataWidth >= 2 * 60 * 60 * 1000 ? 'hour'
                            : 'minute';
        const timeDisplayFormats = {}
        if (format) {
            timeDisplayFormats[unit] = format;
        }
        const options = {
            animation: {
                duration: 0
            },
            plugins: {
                colorschemes: {
                    scheme: 'office.Berlin6'
                }
            },
            responsive: true,
            tooltips: {
                intersect: false,
                axis: 'x'
            },
            hover: {
                mode: 'nearest',
                intersect: false,
                axis: 'x',
                animationDuration: 100
            },
            scales: {
                yAxes: [
                    {
                        id: 'y-axis-l',
                        position: 'left',
                        gridLines: {
                            display: columnsLeft && columnsLeft.length
                        },
                        ticks: {
                            display: columnsLeft && columnsLeft.length
                        }
                    },
                    {
                        id: 'y-axis-r',
                        position: 'right',
                        gridLines: {
                            display: columnsRight && columnsRight.length
                        },
                        ticks: {
                            display: columnsRight && columnsRight.length
                        }
                    }
                ],
                xAxes: [
                    {
                        type: 'time',
                        bounds: 'ticks',
                        time: {
                            displayFormats: timeDisplayFormats,
                            unit: unit
                        },
                        ticks: {
                            maxTicksLimit: maxDate ? 12 : -1,
                            autoSkip: true,
                            maxRotation: 0,
                            minRotation: 0,
                            min: minDate,
                            max: maxDate
                        },
                        distribution: 'linear'
                    }
                ]
            }
        };

        return (
            <div className='container'>
                <span className='datasource-select'>
                    <Dropdown
                        ref={this.leftAxisRef}
                        className='left-datasource-dropdown'
                        placeholder='Left axis data source'
                        fluid
                        multiple
                        search
                        selection
                        loading={isFetching || isLoading}
                        disabled={isFetching || isLoading}
                        options={Object.values(loadedColumns).filter(src => !selectedSettings.columnsRight.includes(src.key)).map(src => src.item).sort((a,b) => a.fullname.toLowerCase().localeCompare(b.fullname.toLowerCase()))}
                        onChange={this.handleLeftColumnSelect}
                        renderLabel={(l) => l.fullname}
                    />
                    <Dropdown
                        ref={this.rightAxisRef}
                        className='right-datasource-dropdown'
                        placeholder='Right axis data source'
                        fluid
                        multiple
                        search
                        selection
                        loading={isFetching || isLoading}
                        disabled={isFetching || isLoading}
                        options={Object.values(loadedColumns).filter(src => !selectedSettings.columnsLeft.includes(src.key)).map(src => src.item).sort((a,b) => a.fullname.toLowerCase().localeCompare(b.fullname.toLowerCase()))}
                        onChange={this.handleRightColumnSelect}
                        renderLabel={(l) => l.fullname}
                    />
                </span>
                <span className='element-limit-select'>
                    <Popup
                        position='top center'
                        trigger={<Header as='h4' textAlign='center' className='helpable-text'>Element count</Header>}
                    >
                        The number of elements to query. If set to <strong>Auto</strong>, elements will be limited to the provided <strong>Time period</strong> and aggregated & displayed automatically.
                        If not, the number of elements to query must be explicitly provided.
                    </Popup>
                    <Grid className='element-limit'>
                    <Checkbox
                        label='Auto'
                        onChange={this.handleAutoElementToggle}
                        className='element-limit-auto'
                        checked={selectedSettings.autoElements}
                    />
                    <Input
                        ref={this.limitInputRef}
                        className='element-limit-input'
                        fluid
                        onChange={this.handleElementInput}
                        value={selectedSettings.rawElements}
                        error={!!selectedSettings.rawElements && !util.isInt(selectedSettings.rawElements)}
                        disabled={selectedSettings.autoElements}
                        placeholder='Limit'
                        onKeyPress={e => {
                            if (e.charCode === 13) {
                                this.plotButton.current.handleClick(e);
                            }
                        }}
                    />
                    </Grid>
                </span>
                <RangePicker defaultRange={60} onRelative={this.selectRelativeRange} onAbsolute={this.selectAbsoluteRange} loading={isLoading}/>

                <span className='admin-launcher'>
                    <span className='account-info'>
                        {userLoading ?
                            <span className='login-loader'>
                                    <Loader className='login-loader' active inline='centered' size='tiny'/>
                                </span>
                            :
                            user ?
                                <Dropdown icon={null} open={userDropdownOpen} onClose={() => this.setState({userDropdownOpen: false})} className='account-dropdown' trigger={
                                    <span className='user-button' onClick={() => this.setState({userDropdownOpen: true})}>
                                        <Icon name='user'/>
                                        <span className='sign-in-text'><strong>{user.username}</strong></span>
                                        <Icon className='range-dropdown-icon' name='angle down'/>
                                    </span>
                                }>
                                    <Dropdown.Menu>
                                        <Dropdown.Item disabled text={<span>Signed in as <strong>{user.username}</strong></span>}/>
                                        <Dropdown.Item icon='edit' text='Change password' onClick={() => this.setState({changePasswordOpen: true})}/>
                                        <Dropdown.Item icon='power' text='Sign out' onClick={this.submitLogout}/>
                                        <Modal
                                            dimmer='inverted'
                                            centered={false}
                                            size='mini'
                                            open={changePasswordOpen}
                                            onClose={() => this.setState({changePasswordOpen: false, changePasswordFailed: false, newPassword: null, newPasswordValidate: null})}>
                                            <Modal.Content>
                                                <Grid centered padded='vertically'>
                                                    <Form loading={changePasswordLoading} onSubmit={this.changePassword} error={changePasswordFailed}>
                                                        <Form.Input style={{display: 'none'}} autoComplete='username'/>
                                                        <Form.Input
                                                            label='New password'
                                                            autoFocus
                                                            onChange={this.setCredentials}
                                                            name='newPassword'
                                                            autoComplete='new-password'
                                                            type='password'
                                                            placeholder='Password'
                                                        />
                                                        <Form.Input
                                                            label='Repeat new password'
                                                            onChange={this.setCredentials}
                                                            name='newPasswordValidate'
                                                            autoComplete='new-password'
                                                            type='password'
                                                            error={(!this.newPasswordValid() && newPasswordValidate && newPasswordValidate.length > 0) ?
                                                                <Label className='flexible-label' pointing>Passwords must match</Label>
                                                                :
                                                                null}
                                                            placeholder='Password'
                                                        />
                                                        <Form.Field disabled={!this.newPasswordValid()} control={Button}>Change password</Form.Field>
                                                        {changePasswordFailed ? <Message attached='bottom' compact error>Operation failed</Message> : null}
                                                    </Form>
                                                </Grid>
                                            </Modal.Content>
                                        </Modal>
                                    </Dropdown.Menu>
                                </Dropdown>
                                :
                                <Modal
                                    dimmer='inverted'
                                    centered={false}
                                    size='mini'
                                    open={loginOpen}
                                    onClose={() => this.setState({loginOpen: false, loginFailed: false, username: null, password: null})}
                                    trigger={
                                        <span onClick={() => this.setState({loginOpen: true})} className='login-button'>
                                    <Icon name='user'/><span className='sign-in-text'>Sign in</span>
                                </span>
                                    }>
                                    <Modal.Content>
                                        <Grid centered padded='vertically'>
                                            <Form loading={loginLoading} onSubmit={this.submitLogin} error={loginFailed}>
                                                <Form.Field>
                                                    <Input onChange={this.setCredentials} name='username' autoFocus autoComplete='current-username' icon='user' iconPosition='left'
                                                           placeholder='Username'/>
                                                </Form.Field>
                                                <Form.Field>
                                                    <Input onChange={this.setCredentials} name='password' autoComplete='current-password' type='password' icon='lock' iconPosition='left'
                                                           placeholder='Password'/>
                                                </Form.Field>
                                                <Form.Field disabled={!username || !password} control={Button}>Sign in</Form.Field>
                                                {loginFailed ? <Message attached='bottom' compact error>Invalid credentials</Message> : null}
                                            </Form>
                                        </Grid>
                                    </Modal.Content>
                                </Modal>
                        }
                    </span>


                    <span className='menu-buttons'>
                    <Button
                        size='small'
                        ref={this.plotButton}
                        loading={isFetching || isLoading}
                        disabled={!this.isPlottable() || isFetching || isLoading || prePlotError != null}
                        onClick={this.handlePlot}
                    >
                        Plot
                    </Button>

                    <Admin woofs={loadedWoofs} user={user}
                           peekWoof={this.peekWoof}
                           onDelete={this.deleteWoof}
                           onCreate={this.createWoof}
                           onUpdate={this.updateWoof}
                           onSync={this.syncWoof}
                           onUpdateConfig={this.updateConfig}
                           loadConfig={this.loadConfig}

                    />
                    </span>
                </span>

                <br style={{clear: 'both'}}/>
                <div className='chart-container' id='chart-wrapper'>
                    <canvas id='cursor'/>
                    <Line ref={this.chartRef} id='data-chart' data={{datasets: datasets}} options={options} redraw={false}/>
                </div>
            </div>
        );
    }
}
