# WoofPlot
Time series extraction, aggregation, and plotting platform. WoofPlot's responsibility is to provide:
1. Frontend web interface for plotting time series data and configuring sources from which to extract data
2. Backend server to keep configured data sources synchronized, extract time series data, and host the frontend

## Requirements
* [yarn](https://classic.yarnpkg.com/en/docs/install)
* [PostgreSQL with TimescaleDB extension](https://docs.timescale.com/latest/getting-started/setup) (if running WoofPlot binary outside of container)
* [Docker](https://docs.docker.com/get-docker/) (if building and running the WoofPlot image)

## Installation

### Centos 8 Stream
```
sudo yum -y install npm

cd ui
npm install yarn
yarn install
yarn run build		#version 1.22.22
npx browserslist@latest --update-db
cd
ln -s ui/build .
```

# Running WoofPlot
```
cd woofplot
python3 woofplot-server.py 
```
