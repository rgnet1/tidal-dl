# Docker file for python simple tidal-dl web server build

FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt update
RUN apt -y install software-properties-common
RUN apt -y install apache2
RUN apt -y install nano


# Python3.9
RUN apt -y install python3

# Install get-pip script
RUN apt -y install python3-pip
COPY requierments.txt .
RUN pip3 install -r requierments.txt
COPY settings.py /usr/local/lib/python3.8/dist-packages/tidal_dl/settings.py

# Http settings
ENV APACHE_RUN_USER www-data
ENV APACHE_RUN_GROUP www-data
ENV APACHE_LOG_DIR /var/log/apache2
ENV APACHE_PID_FILE /var/run/apache2.pid
ENV APACHE_RUN_DIR /var/run/apache2
ENV APACHE_LOCK_DIR /var/lock/apache2
RUN mkdir -p $APACHE_RUN_DIR $APACHE_LOCK_DIR $APACHE_LOG_DIR

RUN mkdir -p /production/www/cgi-bin/download
RUN mkdir -p /production/www/lib
COPY cgi-bin /production/www/cgi-bin
COPY lib /production/www/lib
COPY apache2 /etc/apache2
COPY webpage /var/www/html/
RUN ln -s /etc/apache2/mods-available/cgi.load /etc/apache2/mods-enabled/cgi.load
RUN chgrp www-data /production/www/cgi-bin/
RUN chmod g+rwx /production/www/cgi-bin/
RUN chown -R www-data: /production/www/cgi-bin/download/
RUN chgrp www-data /var/www/
RUN chmod g+rwxs /var/www/

COPY tidal-login.sh .
RUN chmod +x tidal-login.sh
EXPOSE 80

ENTRYPOINT [ "/usr/sbin/apache2" ]
CMD ["-D", "FOREGROUND"]

# Login as www-data user: su -l www-data -s /bin/bash
# edit settings file:  nano /usr/local/lib/python3.8/dist-packages/tidal_dl/settings.py
# change line 37ish to return os.path.abspath("./")