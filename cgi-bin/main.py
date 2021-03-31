#!/usr/bin/python3

print("Content-type: text/html")
print("\n")

import cgi, cgitb
import os
import subprocess

def bash_command(cmd):
    subprocess.Popen(['/bin/bash', '-c', cmd]).wait()

form = cgi.FieldStorage()

if "textcontent" not in form:
    print("Can't find text content")
    f = open("/production/www/cgi-bin/links.txt", "w+")
    f.write("EMPTY")
    f.close()

else:
    # print("<p>link:", form["textcontent"].value)
    f = open("/production/www/cgi-bin/links.txt", "w+")
    f.write(form["textcontent"].value)
    f.close()
    bash_command("python3 tidaldl.py")