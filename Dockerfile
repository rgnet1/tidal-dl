# Docker file for python simple tidal-dl web server build

FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive \
 APACHE_RUN_USER=www-data \
 APACHE_RUN_GROUP=www-data \
 APACHE_LOG_DIR=/var/log/apache2 \
 APACHE_PID_FILE=/var/run/apache2.pid \
 APACHE_RUN_DIR=/var/run/apache2 \
 APACHE_LOCK_DIR=/var/lock/apache2

# Updates and installs
RUN apt update && apt -y install \
    software-properties-common \
    apache2 \
    nano \
    python3 \
    python3-pip

# Copy necessary files into container
COPY copy-files/ ./copy-files/

# set up container enviornment:
RUN pip3 install -r copy-files/requierments.txt &&\
cp copy-files/settings.py /usr/local/lib/python3.8/dist-packages/tidal_dl/settings.py && \
mkdir -p $APACHE_RUN_DIR $APACHE_LOCK_DIR $APACHE_LOG_DIR && \
mkdir -p /production/www/cgi-bin/download/Album && \
mkdir -p /production/www/lib && \
cp -r copy-files/cgi-bin/* /production/www/cgi-bin/ && \
cp -r copy-files/lib/* /production/www/lib/ && \
cp -r copy-files/apache2/* /etc/apache2/ && \
cp -r copy-files/webpage/* /var/www/html/ && \
ln -s /etc/apache2/mods-available/cgi.load /etc/apache2/mods-enabled/cgi.load && \
chgrp www-data /production/www/cgi-bin/ && \
chmod g+rwx /production/www/cgi-bin/ && \
chown -R www-data: /production/www/cgi-bin/download/ && \
chmod 755 production/www/cgi-bin/download/ && \
chgrp www-data /var/www/ && \
chmod g+rwxs /var/www/ && \
cp copy-files/tidal-login.sh . && \
chmod +x tidal-login.sh

EXPOSE 80
ENTRYPOINT [ "/usr/sbin/apache2" ]
CMD ["-D", "FOREGROUND"]

# Login as www-data user: su -l www-data -s /bin/bash
# edit settings file:  nano /usr/local/lib/python3.8/dist-packages/tidal_dl/settings.py