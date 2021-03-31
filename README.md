# rgnet1/tidal-dl

This is a simple web server that allows you to run yaronzz/tidal-dl from a web
browser.

## Getting Started

Manually build image:
```bash
docker build -t tidal-dl .
```
Run image
```bash
docker run -p 8885:80 --name tidal-dl -d \
 -v <your-downlaod-location>:/production/www/cgi-bin/download-d \
 rgnet1/tidal-dl
```

## First Time Use
First time use requires you to enter the container, and link tidal to your account. Run the tidal-login script with the following command:
```bash
docker exec -it tidal-dl ./tidal-login.sh
```

**_Note:_** Make sure you enter ```0``` after linking your account so tidal-dl exits. This is necessary for the
the login script can finish execution

**_Note 2:_** You must use my tidal-login script, because it genrates and then moves the tidal-dl.token.json file to the the proper directory with the
right permissions for tidal-dl to read.


# Usage
You can Access from the below URL after run docker container.  

* [http://localhost:8885](http://localhost:8885)


### References
* [Usage of docker with apache2 and cgi](https://github.com/pyohei/docker-cgi-python)
* [Tidal-dl](https://github.com/yaronzz/Tidal-Media-Downloader)
