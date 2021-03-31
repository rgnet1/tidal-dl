# rgnet1/tidal-dl

This is a simple web server that allows you to run yaronzz/tidal-dl from a web
browser.

## How to use
```bash
# Manually build image
docker build -t tidal-dl .
# run image
docker run -p 8885:80 --name tidal-dl -v <your-downlaod-loc>:/production/www/cgi-bin/download-d rgnet1/tidal-dl
```

## First time use
First time use requires you to enter the container, and link tidal to your account:

```bash
# Enter docker container
docker exec -it  tidal-dl /bin/bash

# run my login script
./tidal-login.sh
```
Folow the onscreen prompts to finish tidal login, and exit the tidal-dl script
by pressing 0 after you are logged in.

You can now exit the contianer with: ```exit ```

**_Note:_** You must use my tidal-login script, because it moves
the tidal-dl.token.json file to the the proper directory with the
right permissions for tidal-dl to read. In the future I hope to
support linking your exising token file.


# Usage
You can Access from the below URL after run docker container.  

* [http://localhost:8885](http://localhost:8885)


### References
* [Usage of docker with apache2 and cgi](https://github.com/pyohei/docker-cgi-python)
* [Tidal-dl](https://github.com/yaronzz/Tidal-Media-Downloader)
