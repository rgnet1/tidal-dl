# @author: Ramzey Ghanaim
# 
#            tidaldl.py
# This program is desinged to automate and downlad all tidal links
# users provide into a text file at one time.
# 
# Instructions: 
#      Copy the links to the songs you want, past them into the
#      text document, and run the code
# 
# Dependencies:
#      pexpect, python3
import os
import subprocess
import pexpect
import sys
import re
from pexpect.expect import searcher_re
ansi_escape = re.compile(rb'\x1B[@-_][0-?]*[ -/]*[@-~]')
FILENAME = "/production/www/cgi-bin/links.txt"
totalSongCount = 0
print("\n")
#                         waitAgain()
#
# This function waits to expect the "enter choice" output from tidaldl
# this output means that the downald is completed or failed, and we are
# waiting for the next song
#
# @param: type - string - type of link we are downloading: album, track 
def waitAgain(type):
    global totalSongCount
    #                       y = 0               y=1
    y = tidal.expect(['.*Enter Choice:.*', '.*SUCCESS.*'],timeout=50)
    
    # Current link is completed. tidal-dl is waiting for next link
    if y == 0:
        print("Finished download from current", type,"\n")
        if type == "track":
            totalSongCount +=1
        return 0

    # successfully download one song, but the next song is downloading
    if y == 1:
        # remove ansi color, and decode byte stream into utf-8 for python
        # compatability
        successString = ansi_escape.sub(b'',tidal.after).decode("utf-8")
        
        # Split string in half at [success], because file name is to the right (index 1)
        # EX:  ".......... [SUCCESS] ..... <Artist> - <songName>.flac ....."
        #  Split string: [ .......... [SUCCESS]  ,  <num> - <Artist> - <songName>.flac .....]
        #                          index 0                    index 1
        #  All songs are at index one 
        songDetails = successString.split('[SUCCESS]')[1]
        
        # [...<num> - <artist> - <songName>.flac ....]
        # songDetails = songDetails.split('-')
        
        # # song number is at index 0
        # songNum = songDetails[0].strip()

        # # artist is at index 1
        # artist = songDetails[1].strip()

        # # song is at index 2
        # song = songDetails[2].split('.flac', 1)[0].strip()

        # print("COMPLETED:", songNum, song, "By:", artist, "\n")
        print("COMPLETED:", songDetails)
        totalSongCount +=1
        return -1

# read file
queue = open(FILENAME, 'r')


# Start up the tidal-dl
tidal = pexpect.spawn("tidal-dl")
x = 1
first = True
for line in queue:
    # print(line.strip())
    type = "unknown"
    if "album" in line:
        type = "album"
    elif "track" in line:
        type = "track"
    elif "playlist" in line:
        type = "playlist"
    elif "video" in line:
        type = "video"
    try:
        print("----------------Starting new download. New", type,"----------------")

        # Only check Enter choice first time, because waitAgain() function
        # checks it after the first time
        if first:
            x = tidal.expect(['.*Enter Choice:.*', '.*Waiting for authorization.*'],timeout=10)
            first = False
        else:
            x = 0
        if x == 0:
            y = -1 
            tidal.send(line.strip() + "\n")
            while y == -1:
                y = waitAgain(type)
            # print("Done with current link")
        if x == 1:
            print(ansi_escape.sub(b'',tidal.before).decode("utf-8"))
            print(ansi_escape.sub(b'',tidal.after).decode("utf-8"))
            print("Waiting for you to register....")
            # sttart interactie mode
            # tidal.interact()
        if x == 2:
            print("Error: timeout\n")
    except pexpect.EOF:
        print("EOF error")
        print(tidal.before)
        print(tidal.after)
    except pexpect.TIMEOUT:
        print("Timeout Error")
        print(tidal.before)
        print(tidal.after)

print("-----------COPLETED ALL SONGS------------------")
print("Total number of songs:", totalSongCount)
queue.close()

tidal.kill(0)
sys.exit()