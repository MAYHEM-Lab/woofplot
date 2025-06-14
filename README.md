# WoofPlot
Time series extraction, aggregation, and plotting platform. WoofPlot's responsibility is to provide:
1. Frontend web interface for plotting time series data and configuring sources from which to extract data
2. Backend server to keep configured data sources synchronized, extract time series data, and host the frontend

## Fast Start
* Use the **pre-made docker container** (Ubuntu 24.04), via these [these instructions](https://docs.google.com/document/d/1nIc00qmNRd9zsD2ApW7BYlDljN3qI2IlRiTh67xi3pM).

## Requirements (for non-docker-container installation)
* [python3 as python](https://www.python.org/downloads/)
* [yarn](https://classic.yarnpkg.com/en/docs/install)
* [PostgreSQL](https://www.postgresql.org)
* * [Configuration and Setup (Centos)](https://www.digitalocean.com/community/tutorials/how-to-install-and-use-postgresql-on-centos-8)
  * [Configuration and Setup (Ubuntu)](https://www.digitalocean.com/community/tutorials/how-to-install-postgresql-on-ubuntu-20-04-quickstart)
* [redis and python rq](https://python-rq.org)
* [CSPOT](https://github.com/MAYHEM-Lab/cspot) -- you need only install the CSPOT tools (not docker), e.g. you can use install-ubuntu-nodocker.sh for Ubuntu distros.

## Installation
```
#install cspot first (using the link above).
cd
git clone git@github.com:MAYHEM-Lab/woofplot.git
```
To use a **pre-made docker container** (Ubuntu 24.04), see [these instructions](https://docs.google.com/document/d/1nIc00qmNRd9zsD2ApW7BYlDljN3qI2IlRiTh67xi3pM).

### Ubuntu (v20.04 and after) Configuration
```
# Ensure you do not have a firewall blocking port 8111.
# Open port 8111 if you are running a firewall via: sudo ufw allow 8111/tcp
sudo apt update; sudo apt -y upgrade; sudo apt -y autoremove
sudo apt install -y python3 python-is-python3 python3-dev redis npm postgresql logrotate build-essential libpq-dev postgresql-contrib python3-virtualenv

# For some versions of ubuntu, you may need this for your particular python version (the below uses python3.8)
sudo apt install -y python3.8-venv

# Setup your environment PATH variable to access the tools
export PATH=${PATH}:/home/ubuntu/.local/bin   #place this in ~/.bashrc also
```
### Centos 8 Stream Configuration
```
# Ensure you do not have a firewall blocking port 8111.
# Turn off the firewall (to test) via: systemctl stop firewalld
sudo yum -y update
sudo yum install -y python3.11 python3.11-devel redis npm  postgresql postgresql-server postgresql-contrib postgresql-devel logrotate
sudo yum groupinstall "Development Tools" -y
sudo update-alternatives --config python   #choose python3.11 and verify its the default with python -V
python -m ensurepip
python -m pip install --upgrade pip
```
### Next Step: Build WoofPlot (regardless of distro)
```
cd ~/woofplot

python -m venv woofplotenv
source woofplotenv/bin/activate
pip install --upgrade pip
pip install sqlalchemy-utils psycopg python-dotenv flask flask-jwt-extended passlib rq flask_cors psycopg2-binary sqlalchemy_orm pytz python-dotenv requests
#if you are using an older distro -- you need to upgrade flask:
pip install --upgrade Flask
deactivate

cd ui
sudo npm install --global yarn
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.1/install.sh | bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh" 
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion" 
nvm install node
nvm install 16
yarn install
yarn run build  #rerun this if/when you change the UI files
cd ..
ln -s ui/build .
```

## Configure WoofPlot (Setup the DB and Environment)
```
# Start the database server if needed, then create the user with superuser privileges
sudo /etc/init.d/postgresql start

# Configure your postgresql database. Links for configuration/setup are above. 
sudo -u postgres createuser --interactive   # username is your login (ubuntu, centos, cloud-user); Y to superuser privileges

# Using psql add a password for this user
# XXX is the username you just added via createuser (it is your login: ubuntu, centos, cloud-user, ...)
# YYY is any strong password for the database -- make sure it is single quotes. 
sudo -u postgres psql postgres
postgres=# ALTER USER XXX WITH PASSWORD 'YYY';
postgres=# \q

# Then create the woofplot dB:
createdb woofplot

cd ~/woofplot
cp env .env    #change XXX and YYY to the values you set above using psql
# You can also change  JWT_SECRET to any string (used to generate secrets for access tokens)
# You can also change CSPOT_DIR to be the full path to your CSPOT utilities (build/bin files)

# Create an admin user in a file called woofplot_seed.py with these contents:
# PWD is the admin password that you will use initially for the woofplot app (you can change it in the app)
users_list = [
    ('admin','PWD',True),
]
# Run the db script to setup the woofplot tables.
# Note that this deletes any tables/data that you have put in the woofplot database from earlier runs.
source woofplotenv/bin/activate
python db.py -c
deactivate
```

# Running WoofPlot
```
cd ~/woofplot
mkdir -p logs
sudo /etc/init.d/postgresql start   #make sure the database is started

# First check that redis-server is running (ps auxww |grep redis-server), if not start it with this:
redis-server --daemonize yes --logfile ./logs/woofplot-redis.log

# Start multiple background workers to load data in parallel
source woofplotenv/bin/activate
rq worker default > ./logs/woofplot-worker1.log 2>&1 &
rq worker default > ./logs/woofplot-worker2.log 2>&1 &

# Start the server
python woofplot-server.py >> ./logs/woofplot-server.log 2>&1 &
```
* Navigate to http://YOUR_IPADDRESS:8111 (you can change the port in .env and restart the woofplot server)
* Be sure to check the logs folder periodically to remove unneeded logs (or setup logrotate to do so)

# Terminating WoofPlot
* Press Ctrl-C on woofplot-server.py if in foreground (else kill its process ID)
* Use ```kill -9 XXX``` to kill the process IDs (XXX) for redis-server and rq worker
* Use ```deactivate``` to exit the python virtual environment
