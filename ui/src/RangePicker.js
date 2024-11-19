import React, {Component} from 'react';
import {Button, Grid, Header, Icon, List, Menu, Popup} from 'semantic-ui-react'
import DatePicker from "react-datepicker";
import {format} from 'date-fns/esm'

import "react-datepicker/dist/react-datepicker.css";

const DATE_FORMAT = 'MMM d, yyyy h:mm aa'
const DATE_FORMAT_SAME_YEAR = 'MMM d, h:mm aa'

const ranges = [
    {
        value: -1,
        text: 'Auto',
        renderOverride: 'Automatic'
    },
    {
        value: 60,
        text: '60 minutes',
        interval: 'minute',
        unit: 'minute'
    },
    {
        value: 6 * 60,
        text: '6 hours',
        interval: 'minute',
        unit: 'hour'
    },
    {
        value: 24 * 60,
        text: '24 hours',
        interval: 'minute',
        unit: 'hour'
    },
    {
        value: 3 * 24 * 60,
        text: '3 days',
        interval: 'hour',
        unit: 'hour',
        format: 'MMM D hA'
    },
    {
        value: 7 * 24 * 60,
        text: '7 days',
        interval: 'hour',
        unit: 'day'
    },
    {
        value: 28 * 24 * 60,
        text: '4 weeks',
        interval: 'day',
        unit: 'week'
    },
    {
        value: 365 * 24 * 60,
        text: '1 year',
        interval: 'week',
        unit: 'month'
    }
];

export default class RangePicker extends Component {
    state = {
        relativeRange: ranges.find(range => range.value === this.props.defaultRange),
        absoluteRange: null,
        showDropdown: false,
        buildingTimeRange: false,
        absoluteStartDate: null,
        absoluteEndDate: null,
        recentRanges: new Set(JSON.parse(localStorage.getItem("recent_ranges")))
    }

    selectAbsoluteStartDate = (date) => {
        const trunc = new Date(date);
        trunc.setSeconds(0, 0);
        this.setState({absoluteStartDate: trunc});
    }

    selectAbsoluteEndDate = (date) => {
        const trunc = new Date(date);
        trunc.setSeconds(0, 0);
        this.setState({absoluteEndDate: trunc});
    }

    componentDidMount() {
        this.props.onRelative(this.state.relativeRange);
    }

    selectRelative = (minutes) => {
        const {onRelative} = this.props;
        const relativeRange = ranges.find(range => range.value === minutes);
        this.setState({relativeRange: relativeRange, absoluteRange: null, absoluteStartDate: null, absoluteEndDate: null})
        this.closeSelection()
        onRelative(relativeRange);
    }

    selectAbsolute = () => {
        const {absoluteStartDate, absoluteEndDate} = this.state;
        this.finalizeAbsoluteRange(absoluteStartDate, absoluteEndDate);
    }

    loadRecentRange = (start, end) => {
        this.finalizeAbsoluteRange(start, end);
    }

    finalizeAbsoluteRange = (start, end) => {
        const {onAbsolute} = this.props;
        const width = (end.getTime() - start.getTime()) / (60 * 1000);

        let unit, interval, format;
        for (let i = 0; i < ranges.length; i++) {
            if (width < ranges[i].value || i === ranges.length - 1) {
                unit = ranges[i - 1].unit;
                interval = ranges[i - 1].interval;
                format = ranges[i - 1].format;
                break;
            }
        }

        const absoluteRange = {
            start: start,
            end: end,
            unit: unit,
            interval: interval,
            format: format
        }
        const newRanges = new Set(this.state.recentRanges);
        newRanges.delete(start.getTime() + ":" + end.getTime());
        newRanges.add(start.getTime() + ":" + end.getTime());
        localStorage.setItem("recent_ranges", JSON.stringify([...newRanges]))
        this.setState({relativeRange: null, absoluteRange: absoluteRange, recentRanges: newRanges})
        this.closeSelection()
        onAbsolute(absoluteRange);
    }

    showSelection = () => {
        this.setState({showDropdown: true})
        if (this.state.absoluteRange) {
            this.setState({
                absoluteStartDate: this.state.absoluteRange.start, absoluteEndDate: this.state.absoluteRange.end
            });
        }
    }

    closeSelection = () => {
        this.setState({showDropdown: false, buildingTimeRange: false, absoluteStartDate: null, absoluteEndDate: null});
    }

    resetDateSelection = () => {
        this.setState({absoluteStartDate: null, absoluteEndDate: null});
    }

    showCustom = () => {
        this.setState({buildingTimeRange: true});
    }

    formatDate = (date) => {
        if (date.getFullYear() === new Date().getFullYear()) {
            return format(date, DATE_FORMAT_SAME_YEAR);
        }
        return format(date, DATE_FORMAT);
    }

    startRef = React.createRef();
    endRef = React.createRef();

    render() {
        return (
            <span className='range-select'>
                <Popup
                    position='top center'
                    trigger={<Header as='h4' textAlign='center' className='helpable-text'>Time period</Header>}
                >
                    The time range to limit queries to. If set to <strong>Auto</strong>, the time range will be automatically selected to fit all queried elements.
                    However, if <strong>Element count</strong> is also set to <strong>Auto</strong>, this option will select elements from the past hour.
                </Popup>
                <Popup
                    open={this.state.showDropdown}
                    onClose={this.closeSelection}
                    className='range-dropdown-menu'
                    position='bottom left'
                    basic
                    flowing
                    on='click'
                    trigger={
                        <div className='range-dropdown' onClick={this.showSelection}>
                        <span className='range-description'>
                            <Icon className='range-icon' name='clock outline'/>
                            {/*Since 7 days ago*/}
                            {this.state.relativeRange ?
                                this.state.relativeRange.renderOverride ?
                                    <strong>{this.state.relativeRange.renderOverride}</strong> :
                                    <>Since <strong>{this.state.relativeRange.text}</strong> ago</> :
                                <>from <strong>{this.formatDate(this.state.absoluteRange.start)}</strong> to <strong>{this.formatDate(this.state.absoluteRange.end)}</strong></>
                            }
                            <Icon className='range-dropdown-icon' name='angle down'/>
                        </span>
                        </div>
                    }
                >
                    <Popup.Content>
                        <Grid>
                            <Grid.Column width={4}>
                                <Menu vertical className='range-listing'>
                                    {ranges.map(range => {
                                        const active = this.state.relativeRange && range.value === this.state.relativeRange.value && !(this.state.buildingTimeRange || this.state.absoluteRange)
                                        return (
                                            <Menu.Item
                                                active={active}
                                                key={range.value}
                                                className='range-middle-item'
                                                onClick={() => this.selectRelative(range.value)}
                                            >
                                                <span>{active ?
                                                    <strong>{range.text}</strong> :
                                                    range.text
                                                }

                                                </span>
                                            </Menu.Item>
                                        );
                                    })}
                                    <Menu.Item
                                        className='range-last-item'
                                        active={this.state.buildingTimeRange || !!this.state.absoluteRange}
                                        onClick={this.showCustom}
                                    >
                                        <span>Custom</span><Icon name='angle right'/>
                                    </Menu.Item>
                                </Menu>
                            </Grid.Column>
                            {this.state.buildingTimeRange || this.state.absoluteRange ? <Grid.Column width={12}>
                                <div className='range-interval-builder'>
                                    <div className='range-interval-builder-container'>
                                        <Grid>
                                            <Grid.Row textAlign='center' centered>
                                                <Header>Custom Time Period</Header>
                                            </Grid.Row>
                                            <Grid.Row textAlign='center' centered>
                                                <DatePicker
                                                    ref={this.startRef}
                                                    className='date-pick-input'
                                                    dateFormat={DATE_FORMAT}
                                                    showTimeSelect
                                                    filterTime={time => {
                                                        if (!this.state.absoluteEndDate) {
                                                            return true
                                                        }
                                                        const currentDay = new Date(this.startRef.current.state.preSelection);
                                                        currentDay.setHours(time.getHours(), time.getMinutes(), time.getSeconds(), time.getMilliseconds());

                                                        return this.state.absoluteEndDate > currentDay;
                                                    }}
                                                    maxDate={this.state.absoluteEndDate ? new Date(this.state.absoluteEndDate - 1) : null}
                                                    openToDate={this.state.absoluteEndDate ? new Date(this.state.absoluteEndDate - 1) : null}
                                                    selected={this.state.absoluteStartDate}
                                                    onChange={this.selectAbsoluteStartDate}
                                                    placeholderText="Select start date"
                                                />
                                                <Icon className='time-range-icon' size='large' name='arrow right'/>
                                                <DatePicker
                                                    ref={this.endRef}
                                                    className='date-pick-input'
                                                    dateFormat={DATE_FORMAT}
                                                    showTimeSelect
                                                    filterTime={time => {
                                                        if (!this.state.absoluteStartDate) {
                                                            return true
                                                        }
                                                        const currentDay = new Date(this.endRef.current.state.preSelection);
                                                        currentDay.setHours(time.getHours(), time.getMinutes(), time.getSeconds(), time.getMilliseconds());

                                                        return this.state.absoluteStartDate < currentDay;
                                                    }}
                                                    minDate={this.state.absoluteStartDate ? new Date(this.state.absoluteStartDate.getTime() + 31 * 60 * 1000) : null}
                                                    openToDate={this.state.absoluteStartDate ? new Date(this.state.absoluteStartDate.getTime() + 31 * 60 * 1000) : null}
                                                    selected={this.state.absoluteEndDate}
                                                    onChange={this.selectAbsoluteEndDate}
                                                    placeholderText="Select end date"
                                                />
                                            </Grid.Row>
                                            <Grid.Row textAlign='center' centered className='range-buttons-row'>
                                                <Button
                                                    size='tiny'
                                                    onClick={this.resetDateSelection}
                                                >
                                                    Reset
                                                </Button>
                                                <Button
                                                    primary
                                                    size='tiny'
                                                    disabled={this.state.absoluteEndDate === null || this.state.absoluteStartDate === null}
                                                    onClick={this.selectAbsolute}
                                                >
                                                    Select
                                                </Button>
                                            </Grid.Row>
                                            <Grid.Row textAlign='center' centered>
                                                <div className='small-header-wrapper'>
                                                    <span className='small-header-text'>Recent</span>
                                                </div>
                                            </Grid.Row>
                                            <Grid.Row textAlign='center' className='recent-absolute-ranges'>
                                                <List relaxed selection>
                                                    {[...this.state.recentRanges].reverse().slice(0, 4).map(range => {
                                                        const parts = range.split(":");
                                                        const startDate = new Date(parseInt(parts[0]));
                                                        const endDate = new Date(parseInt(parts[1]));
                                                        return <List.Item className='recent-range' key={JSON.stringify(range)} onClick={() => this.loadRecentRange(startDate, endDate)}>
                                                            from <strong>{this.formatDate(startDate)}</strong> to <strong>{this.formatDate(endDate)}</strong>
                                                        </List.Item>
                                                    })}
                                                </List>
                                            </Grid.Row>
                                        </Grid>
                                    </div>
                                </div>
                            </Grid.Column> : null
                            }
                        </Grid>

                    </Popup.Content>

                </Popup>

            </span>
        );
    }
}