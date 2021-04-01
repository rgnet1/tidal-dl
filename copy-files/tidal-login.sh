#!/bin/bash
tidal-dl
echo "Moving login token to proper directory"
cp ~/.tidal-dl.token.json /production/www/cgi-bin/.tidal-dl.token.json
echo "Changing file permission for tidal-dl access"
chmod 666 /production/www/cgi-bin/.tidal-dl.token.json