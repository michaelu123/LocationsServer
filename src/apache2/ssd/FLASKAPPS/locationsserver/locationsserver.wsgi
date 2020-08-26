#!/usr/bin/python
import logging
import sys
import os
logging.basicConfig(stream=sys.stderr)
sys.path.insert(0,"/ssd/FLASKAPPS/locationsserver/venv/lib/python3.7/site-packages")
sys.path.insert(0,"/ssd/FLASKAPPS/locationsserver")
logging.error("cwd1 %s", os.getcwd())
os.chdir("/ssd/FLASKAPPS/locationsserver")
logging.error("cwd2 %s", os.getcwd())
from app import app as application
