# rgnet1/tidal-dl
![GitHub Workflow Status](https://img.shields.io/github/workflow/status/rgnet1/tidal-dl/Build)
![Docker Pulls](https://img.shields.io/docker/pulls/rgnet1/tidal-dl)

This is a simple web server that allows you to run yaronzz/tidal-dl
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
      - '~/download/:/production/www/cgi-bin/download/Album/'

```

### docker cli

```
docker run -d \
  --name=tidal-dl \
  -p 8885:80 \
  -v ~/download/:/production/www/cgi-bin/download/Album/ \
  rgnet1/tidal-dl

```
## Application Setup
First time use requires you to enter the container, and link tidal to your account. Run the tidal-login script, buitl inside the container. 

### docker cli
Run the login script with docker cli:
```bash
docker exec -it tidal-dl ./tidal-login.sh
```

### unRAID
Open the container's console form unRAID UI and run:
```bash
./tidal-login.sh
```


**_Note:_** Make sure you enter ```0``` after linking your account so tidal-dl exits. This is necessary for the
the login script can finish execution

**_Note 2:_** You must use my tidal-login script, because it genrates and then moves the tidal-dl.token.json file to the the proper directory with the
right permissions for tidal-dl to read.



You can Access from the below URL after run docker container:  

* [http://localhost:8885](http://localhost:8885)

## Parameters

Container images are configured using parameters passed at runtime (such as those above). These parameters are separated by a colon and indicate `<external>:<internal>` respectively. For example, `-p 8885:80` would expose port `80` from inside the container to be accessible from the host's IP on port `8885` outside the container.


| Parameter | Function |
| :----: | --- |
| `-p 80` | Tidal-dl Web UI |
| `-v /production/www/cgi-bin/download/` | Contains the download directory for tidal-dl |

### Tidal-dl settings
Currently we use a static tidal-dl settings I plan on making enviornmental variables out of these settings at some point soon. But here is the defualt/current settings:
```json
"addAlbumIDBeforeFolder": false,
"addExplicitTag": true,
"addHyphen": true,
"addYear": true,
"albumFolderFormat": "{ArtistName}/{AlbumTitle}",
"artistBeforeTitle": false,
"audioQuality": "Master",
"checkExist": true,
"downloadPath": "/production/www/cgi-bin/download/",
"getAudioQuality": null,
"getDefaultAlbumFolderFormat": null,
"getDefaultTrackFileFormat": null,
"getVideoQuality": null,
"includeEP": false,
"language": "0",
"multiThreadDownload": true,
"onlyM4a": false,
"read": null,
"save": null,
"saveCovers": true,
"showProgress": true,
"trackFileFormat": "{TrackNumber}-{TrackTitle}",
"usePlaylistFolder": true,
"useTrackNumber": true,
"videoQuality": "P1080"
```
**_Note:_** Do not change the `downloadPath` variable inside the contianer's tidal-dl.json settings. The current path has specfic linux permissions that allows web users to write to.
If you change the path, you can change the outside of the container with volume maping.


## Supported Architectures
The architectures supported by this image are:

| Architecture | Tag |
| :----: | --- |
| amd64 | latest |
| arm64  | latest |
| arm  | latest |
### References
* [Usage of docker with apache2 and cgi](https://github.com/pyohei/docker-cgi-python)
* [Tidal-dl](https://github.com/yaronzz/Tidal-Media-Downloader)
