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
sudo yum install -y python3.11 python3.11-devel redis npm  postgresql postgresql-server postgresql-contrib postgresql-devel logrotate
sudo yum groupinstall "Development Tools" -y
sudo npm install --global yarn
sudo update-alternatives --config python   #choose python3.11 and verify its the default with python -V
python3.11 -m ensurepip
python3.11 -m pip install sqlalchemy-utils psycopg python-dotenv flask flask-jwt-extended passlib rq flask_cors psycopg2 sqlalchemy_orm python-dotenv requests

# Next: Configure your postgresql database. Links for configuration/setup are above. 
# Add a superuser with username and password for your default login (i.e. centos, ubuntu, cloud-user).
# You will add the username and password to your .env file below.
sudo -u postgres createuser --interactive

cd woofplot
cp env .env
# Next: edit .env to replace XXX and YYY with your postgresql username and password, respectively.

# Next: build the UI
cd ui
yarn install
yarn run build
cd ..
ln -s ui/build .
```

# Running WoofPlot
```
cd woofplot
mkdir -p logs

# First check that redis-server is running (ps auxww |grep redis-server), if not start it with this:
redis-server --daemonize yes --logfile ./logs/woofplot-redis.log &

rq worker default > ./logs/woofplot-worker1.log 2>&1 &
rq worker default > ./logs/woofplot-worker2.log 2>&1 &

#edit file .env (use env as an example, replace XXX and YYY with your postgresql username and password)
python woofplot-server.py 
```
* Navigate to http://YOUR_IPADDRESS:8111 (you can change the port in .env and restart the woofplot server)

# Terminating WoofPlot
```
press Ctrl-C on woofplot-server.py
use kill -9 to kill the process IDs for redis-server and rq worker
```
