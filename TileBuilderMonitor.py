#!/usr/bin/env python3.10


import subprocess
import json
from pathlib import Path
import os
import re

validEntry = []

currentUsers_path = "/tool/aticad/1.0/flow/current_users.json"
os.makedirs("tmp_TileBuilderMonitor",exist_ok=True)

paramsNeeded = ["TECHNO_NAME","FLOW_DIR"]

def getUser():
    try:
        result = subprocess.run(["printenv", "USER"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        user = result.stdout.strip()
        return user
    except subprocess.CalledProcessError as e:
        print("printenv command failed:", e.stderr.strip())
        exit(1)

# The function above uses linux commands to get User name from enviornmental variable

def getParams(data):
    try:
        params_path = os.path.join(data["basedir"], "params.json")
        with open(params_path, 'r') as params_file:
            params = json.load(params_file)
        for parameter in paramsNeeded:
            data[parameter] = params["params"][parameter]
        return data
    except FileNotFoundError:
        print(f"File not found: {params_path}")
        return None
#The function above retrieves parameters from the params.json file . Designed in a way thats scalable for adding more and more params by just appending 
# to the paramsNeeded list
#these params are appended to the dictionary created by loading the current_users.json file

def getBackend(user):
    if not os.path.exists(currentUsers_path):
        print("File not found.")
        exit(1)
    else:
        with open(currentUsers_path, 'r') as file:
            for line in file:
                data = json.loads(line)
                if data["username"] == user:
                     data = getParams(data)
                     validEntry.append(data)
    with open("tmp_TileBuilderMonitor/tmp.json", 'w') as file:
       file.write(json.dumps(validEntry, indent=4))

# this func gets the info needed from the current_users.json file for the user calling the script and appends any needed params to the loaded dictionary
# the data is then written to a "BACKEND" json file that will be accessed later so we can display it in our gui 

def main():
    getBackend(user=getUser())

if __name__ == "__main__":
    main()
