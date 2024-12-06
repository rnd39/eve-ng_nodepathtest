# Node connecitivty testing tool for use in EVE-NG with the eve-gui-server:latest 

This script provides a simple way to deploy client/drone nodes in your eve-ng lab, and then ping and traceroute every other node thats added in a full mesh.

Inspired from https://ring.nlnog.net/ ring ping.

## Clone repo

`git clone https://github.com/rnd39/eve-ng_nodepathtest.git /opt/nodepathtest/`

## Create a new apache virtual server

Create the .conf file with the required settings, the client directory to serve the client script on HTTP port 81.

`vi /etc/apache2/sites-available/nodepathtest.conf`

Paste in the following:

```
<VirtualHost *:81>
DocumentRoot /opt/nodepathtest/client
</VirtualHost>
```

Enable apache to list on port 81:

`echo >> /etc/apache2/ports.conf "Listen 81"`

Provision the site in apache:

`sudo a2ensite nodepathtest.conf`

Finaly restart apache to enable the site:

`sudo systemctl reload apache2`

## Create a system service unit for the server script:

Create a service file:

`vi /etc/systemd/system/pathcheck.service`

Paste in the following:

```
[Unit]
Description=Custom Python Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/nodepathtest/server.py
WorkingDirectory=/opt/nodepathtest/server
User=www-data
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## Enable to start on boot and start server

`sudo systemctl daemon-reload`

`sudo systemctl enable pathcheck.service`

`sudo systemctl start pathcheck.service`

## Enable Client Script auto-download and execute 

Create some eve-gui-server:latest docker images, and inside the startup config of each, ammend the IP, gateway and DNS as required and execute the client script:

```
# Set ip address and Default route
ip addr add 192.168.101.11/24 dev eth0 || true
ip route add default via 192.168.101.1 || true
# Set DNS server
cat > /etc/resolv.conf << EOF
nameserver 8.8.8.8
EOF
/bin/bash -c "$(curl -fsSL http://172.17.0.1:81/client_install.sh)"
```
## How to use

Navigate to your eve server on port :50000 i.e. http://192.168.1.10:50000

Start each of the docker:gui nodes in your eve-ng lab