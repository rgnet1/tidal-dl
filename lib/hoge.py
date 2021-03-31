"""test script."""
import platform

def hoge():
   versions = platform.python_version_tuple()
   return "<h1>Python{}.{}</h1>".format(versions[0], versions[1])
