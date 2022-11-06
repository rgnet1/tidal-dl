# rgnet1/tidal-dl
[![GitHub Workflow Status](https://github.com/docker/buildx/workflows/build/badge.svg)](https://img.shields.io/github/workflow/status/rgnet1/tidal-dl/Build)
![Docker Pulls](https://img.shields.io/docker/pulls/rgnet1/tidal-dl)

This is a simple web server that allows you to run yaronzz/Tidal-Media-Downloader
from a web browser. You must have an active tidal subscription.

## Usage
Here are some example snippets to help you get started creating a container.
### docker-compose ([recommended](https://docs.linuxserver.io/general/docker-compose))

Compatible with docker-compose v3 schemas.

```yaml
version: "3"

services:
  tidal-dl:
    container_name: tidal-dl
    image: rgnet1/tidal-dl:latest
    ports:
      - "8885:80"
    volumes:
      - '~/download/:/production/www/cgi-bin/download/'
      - '~/configuration/:/production/www/cgi-bin/configuration/'

```

### docker cli

```
docker run -d \
  --name=tidal-dl \
  -p 8885:80 \
  -v ~/download/:/production/www/cgi-bin/download/ \
  -v ~/configuration/:/production/www/cgi-bin/configuration/ \
  rgnet1/tidal-dl

```
**_Note:_** If you run into issues running the container, please try using
privliged mode by adding the flag ```--privileged``` to docker cli or 
```privileged: true``` to docker-compose. Debian based hosts will need privleged mode.

## Application Setup
### Set up with existing tidal-dl configuration
Only the downloads directory volume map is required. If you want to keep your tidal configuration
persistant so you don't have to log in every time you star the container, you must map
the configuration folder. If you are provideding your own configuration you must place 
the two files (.tidal-dl.json and .tidal-dl.token.json) in the configuration folder

| Your host location | Container location (don't change) | Notes |
| :----: | --- | --- |
| ~/download/  | /production/www/cgi-bin/download/ | Files will download here
| ~/configuration/ | /production/www/cgi-bin/configuration/ | .tidal-dl.json and .tidal-dl.token.json will be placed here


**_Note:_** Just volume mount the configuration folder, and make sure your config file and token file are in it. No need to volume mount the files seperatly. 

### Set up via container login
If you wish to start fresh and log into tidal you can. Simply insert a link and try to download it.

If you are not logged
into tidal, your login link will be generated for you as you try to download a song. You will need to copy and paste that link into a web browser to
login. 

Feel free to open an issue if you have issues logging in.

You can Access from the below URL after run docker container:  

* [http://localhost:8885](http://localhost:8885)

## Parameters

Container images are configured using parameters passed at runtime (such as those above). These parameters are separated by a colon and indicate `<external>:<internal>` respectively. For example, `-p 8885:80` would expose port `80` from inside the container to be accessible from the host's IP on port `8885` outside the container.


| Parameter | Function |
| :----: | --- |
| `-p 80` | Tidal-dl Web UI (required)|
| `-v /production/www/cgi-bin/download/` | Contains the download directory for tidal-dl (required)|
| `-v /production/www/cgi-bin/configuration/` | Contains tidal-dl settings (optional but recommended) |



### Tidal-dl settings
We use default tidal-dl settings if you do not volume mount your own settings. If you wish to
change the tidal-dl settings, you must map the configuration folder and run the container.
Then you can modify the tidal-dl settings file.

**_Note:_** Never change the `downloadPath` variable inside the contianer's tidal-dl.json settings. The current path has specfic linux permissions that allows web users to write to.
Use volume mapping to map this required directory to your
directory of choice.


## Supported Architectures
The architectures supported by this image are:

| Architecture | Tag |
| :----: | --- |
| amd64 | latest |
| arm64  | latest |
| arm  | latest |

## Docker Hub Link
You can find this project on Docker Hub [here](https://hub.docker.com/repository/docker/rgnet1/tidal-dl)

### References
* [Usage of docker with apache2 and cgi](https://github.com/pyohei/docker-cgi-python)
* [Tidal-dl](https://github.com/yaronzz/Tidal-Media-Downloader)
