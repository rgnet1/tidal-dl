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
docker run -p 8885:80 --name tidal-dl -v <your-downlaod-location>:/production/www/cgi-bin/download-d rgnet1/tidal-dl
```

## First Time Use
First time use requires you to enter the container, and link tidal to your account:
1. Enter the docker container
    ```bash
    docker exec -it  tidal-dl /bin/bash
    ```
2. Run login script
    ```bash
    ./tidal-login.sh
    ```
    Folow the onscreen prompts to finish tidal login, and exit the tidal-dl script
by pressing 0 after you are logged in.

3. You can now exit the contianer with:
    ```bash
    exit
    ```

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
