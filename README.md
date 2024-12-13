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
* [CSPOT](https://github.com/MAYHEM-Lab/cspot) -- you need only install the CSPOT tools (not docker), e.g. you can use install-ubuntu-nodocker.sh for Ubuntu distros.

## Installation
```
#install cspot first (using the link above).
git clone git@github.com:MAYHEM-Lab/woofplot.git
```

### Ubuntu 22.04 Configuration
```
# Ensure you do not have a firewall blocking port 8111.
# Open port 8111 if you are running a firewall via: sudo ufw allow 8111/tcp
sudo apt update; sudo apt -y upgrade; sudo apt -y autoremove
sudo apt install -y python3 python-is-python3 python3-dev redis npm postgresql logrotate build-essential libpq-dev postgresql-contrib python3-virtualenv
export PATH=${PATH}:/home/ubuntu/.local/bin   #place this in ~/.bashrc also
```
### Centos 8 Stream Configuration
```
# Ensure you do not have a firewall blocking port 8111.
# Turn off the firewall (to test) via: systemctl stop firewalld
sudo yum -y update
sudo yum install -y python3.11 python3.11-devel redis npm  postgresql postgresql-server postgresql-contrib postgresql-devel logrotate
sudo yum groupinstall "Development Tools" -y
sudo npm install --global yarn
sudo update-alternatives --config python   #choose python3.11 and verify its the default with python -V
python -m ensurepip
python -m pip install --upgrade pip
```
### Remaining Configuration (regardless of distro)
```
# Configure your postgresql database. Links for configuration/setup are above. 
# You will add the username and password to your .env file below.
# Add a superuser with the username for your default login (i.e. centos, ubuntu, cloud-user). 
sudo -u postgres createuser --interactive

# Using the psql command, add a password for the user you just added (change XXX and YYY in the ALTER psql command):
psql postgres
postgres=# ALTER USER XXX WITH PASSWORD 'YYY';
postgres=# \q
createdb woofplot

cd woofplot
sudo npm install --global yarn

python -m venv woofplotenv
source woofplotenv/bin/activate
pip install --upgrade pip
pip install sqlalchemy-utils psycopg python-dotenv flask flask-jwt-extended passlib rq flask_cors sqlalchemy_orm python-dotenv requests
deactivate

```

### Building Woofplot
```
cd woofplot
source woofplotenv/bin/activate
cp env .env
# Next: edit .env to replace XXX and YYY with your postgresql username and password, respectively.  Also change the string in JWT_SECRET so that your own secrets are generated correctly and securely.

# Create an admin user in a file called woofplot_seed.py with these contents (change YYY to a strong password of your choosing):
users_list = [
    ('admin','YYY',True),
]
# Run the db script to setup the woofplot tables. Note that this deletes any tables/data that you have put in the woofplot database from earlier runs.
python db.py -c

# Next: build the UI
cd ui
yarn install
yarn run build  #rerun this if/when you change the UI files
cd ..
ln -s ui/build .
```

# Running WoofPlot
```
cd woofplot
mkdir -p logs

# First check that redis-server is running (ps auxww |grep redis-server), if not start it with this:
redis-server --daemonize yes --logfile ./logs/woofplot-redis.log

rq worker default > ./logs/woofplot-worker1.log 2>&1 &
rq worker default > ./logs/woofplot-worker2.log 2>&1 &

#edit file .env (use env as an example, replace XXX and YYY with your postgresql username and password)
python woofplot-server.py 
```
* Navigate to http://YOUR_IPADDRESS:8111 (you can change the port in .env and restart the woofplot server)

# Terminating WoofPlot
* Press Ctrl-C on woofplot-server.py
* Use ```kill -9 XXX``` to kill the process IDs (XXX) for redis-server and rq worker
```
