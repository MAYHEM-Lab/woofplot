# WoofPlot
Time series extraction, aggregation, and plotting platform. WoofPlot's responsibility is to provide:
1. Frontend web interface for plotting time series data and configuring sources from which to extract data
2. Backend server to keep configured data sources synchronized, extract time series data, and host the frontend

## Requirements
* [python3 as python](https://www.python.org/downloads/)
* [yarn](https://classic.yarnpkg.com/en/docs/install)
* [PostgreSQL](https://www.postgresql.org)
* * [Configuration and Setup (Centos)](https://www.digitalocean.com/community/tutorials/how-to-install-and-use-postgresql-on-centos-8)
  * [Configuration and Setup (Ubuntu)](https://www.digitalocean.com/community/tutorials/how-to-install-postgresql-on-ubuntu-20-04-quickstart)
* [redis and python rq](https://python-rq.org)

## Installation
```git clone git@github.com:MAYHEM-Lab/woofplot.git```

### Centos 8 Stream
```
sudo yum install -y python3-devel redis npm  postgresql postgresql-server postgresql-contrib postgresql-devel logrotate
cd woofplot
npm install yarn
pip install sqlalchemy-utils psycopg python-dotenv flask flask-jwt-extended passlib rq

# Next: Configure your postgresql database. Links for configuration/setup are above. 
# Add a superuser with username and password for your default login (i.e. centos, ubuntu, cloud-user).
# You will add the username and password to your .env file below.
sudo -u postgres createuser --interactive

cp env .env
#edit .env to replace XXX and YYY with your postgresql username and password, respectively.

#Next: build the UI
cd ui
yarn install
yarn run build		#version 1.22.22
npx browserslist@latest --update-db
cd
ln -s ui/build .
```

# Running WoofPlot
```
cd woofplot
redis-server --daemonize yes --logfile ./woofplot-redis.log &
rq worker default > ./woofplot-worker1.log 2>&1 &
rq worker default > ./woofplot-worker2.log 2>&1 &

#edit file .env (use env as an example, replace XXX and YYY with your postgresql username and password)
python woofplot-server.py 
```
* Navigate to http://IPADDRESS:8111 (you can change the port in .env and restart the woofplot server)

# Terminating WoofPlot
```
press Ctrl-C on woofplot-server.py
use kill -9 to kill the process IDs for redis-server and rq worker
```
