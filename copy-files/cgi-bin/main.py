#!/usr/bin/python3 -u

from sys import stdout
import time

import sys, time


print('Content-type: text/html\r\n\r')
# print("Content-type:text/plain;charset=utf-8\n\n") 


import cgi, cgitb
import os, sys
import subprocess

sys.stdout.flush()

# def bash_command(cmd):
#     subprocess.Popen(['/bin/bash', '-c', cmd]).wait()

form = cgi.FieldStorage()

if "textcontent" not in form:
    sys.stdout.write("Can't find text content")
    sys.stdout.flush()
    f = open("/production/www/cgi-bin/links.txt", "w+")
    f.write("EMPTY")
    f.close()

else:
    # print("<p>link:", form["textcontent"].value)
    f = open("/production/www/cgi-bin/links.txt", "w+")
    f.write(form["textcontent"].value)
    f.close()
    import tidaldl.py