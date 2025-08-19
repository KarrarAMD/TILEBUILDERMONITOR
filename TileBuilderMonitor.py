#!/usr/bin/env python3.10


import subprocess
import json
from pathlib import Path
import os
import re
from tkinter.tix import STATUS

#self.validRuns = []

currentUsers_path = "/tool/aticad/1.0/flow/current_users.json"
os.makedirs("tmp_TileBuilderMonitor",exist_ok=True)

paramsNeeded = ["TECHNO_NAME","FLOW_DIR","TB_SRV_DIR"]



class Monitor():
    
    def __init__(self):
        self.validWorkSpaces = []
        self.validRuns = []
        self.User = self.getUser()

    def getUser(self):
        try:
            result = subprocess.run(["printenv", "USER"], text=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            user = result.stdout.strip()
            return user
        except subprocess.CalledProcessError as e:
            print("printenv command failed:", e.stderr.strip())
            exit(1)

    def getAllRuns(self):
        
        user = self.User
        if not os.path.exists(currentUsers_path):
            print("File not found.")
            exit(1)
        else:
            with open(currentUsers_path, 'r') as file:
                for line in file:
                    data = json.loads(line)
                    if data["username"] == user:
                         self.validRuns.append(Run(data))
                print(f"\nFound {len(self.validRuns)} Run Areas found for user: {user}\n")
                for run in self.validRuns:
                    run.getParams()            
    
    def getWorkSpaces(self):
        print("Getting workspaces...")
        # Build mapping from FLOW_DIR to WorkSpace
        workspace_map = {}
        unique_flow_dirs = set(run.dictionary["FLOW_DIR"] for run in self.validRuns if "FLOW_DIR" in run.dictionary)
        for flow_dir in unique_flow_dirs:
            workspace_map[flow_dir] = WorkSpace(flow_dir)
        # Assign each run to the correct workspace
        for run in self.validRuns:
            flow_dir = run.dictionary.get("FLOW_DIR")
            if flow_dir in workspace_map:
                workspace_map[flow_dir].validRuns.append(run)
            else: 
                print("Anomaly detected: Run with FLOW_DIR not found in workspace map")
                print(f"Run details: {run.dictionary}")
        self.validWorkSpaces = list(workspace_map.values())   
        for workspace in self.validWorkSpaces:
            workspace.getStatus()

    def WriteToJson(self):
        print("Writing to Json")
        with open("tmp_TileBuilderMonitor/tmp.json", 'w') as file:
            for workspace in self.validWorkSpaces:
                for run in workspace.validRuns:
                    file.write(json.dumps(run.dictionary, indent=4))

    

class WorkSpace():
        def __init__(self, flow_dir):
             self.validRuns=[]
             self.FLOW_DIR = flow_dir
             print(f"Initialized WorkSpace for FLOW_DIR: {flow_dir}\n\n")

        def printRuns(self):
            for run in self.validRuns:
                print(f"Run: {run.dictionary}\n\n")

        def getStatus (self) :
             if "TB_SRV_DIR" in self.validRuns[0].dictionary :
                cmd = f"source {self.validRuns[0].dictionary['TB_SRV_DIR']}/.cshrc"
                subprocess.run(cmd, text=True, shell=True)
                for STATUS in ["FAILED", "RUNNING"]:     
                    cmd = f"serascmd -find_jobs 'status=={STATUS}' -report 'name dir'"
                    #raw_status = subprocess.run(cmd, text=True, shell=True)
                    #print(f"\nTARGETS {STATUS} ,FLOW_DIR {self.FLOW_DIR}: {raw_status.stdout}\n")
             else :
                print(f"Failed to get status for: {self.FLOW_DIR}")
                print("TB_SRV_DIR not found in run dictionary, skipping source command")

                # for line in raw_status:
                #     print(line)


                 # need to map the run information to the individual runs , specially running targets and failing targets    
class Run():
    def __init__(self,json):
    
        self.dictionary = json
        self.validityFlag = True
        self.RUNNING = []
        self.FAILED = []
        self.ACTIVE = False
        self.ERROR = False

    def getParams(self):
        try:
            params_path = os.path.join(self.dictionary["basedir"], "params.json")
            with open(params_path, 'r') as params_file:
                params = json.load(params_file)

                for parameter in paramsNeeded:
                        self.dictionary[parameter] = params["params"][parameter]
                    
        except FileNotFoundError:
            print(f"File not found: {params_path}")
            self.validityFlag = False
    

def main():


   TileBuilderMonitor = Monitor()
   TileBuilderMonitor.getAllRuns()
   TileBuilderMonitor.getWorkSpaces()
   for workspace in TileBuilderMonitor.validWorkSpaces:
         workspace.printRuns()
   TileBuilderMonitor.WriteToJson()



    

if __name__ == "__main__":
    main()





