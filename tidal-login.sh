#!/bin/bash
tidal-dl
cp ~/.tidal-dl.token.json /production/www/cgi-bin/.tidal-dl.token.json
chmod 666 /production/www/cgi-bin/.tidal-dl.token.json