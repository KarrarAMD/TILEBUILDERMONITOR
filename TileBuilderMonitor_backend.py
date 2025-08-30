import cmd
from concurrent import futures
import subprocess
import json
from pathlib import Path
import os
import re
import time
from tkinter.tix import STATUS
from unittest import result
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from collections import defaultdict
 

currentUsers_path = "/tool/aticad/1.0/flow/current_users.json"
os.makedirs("tmp_TileBuilderMonitor",exist_ok=True)

paramsNeeded = ["TECHNO_NAME","FLOW_DIR","TB_SRV_DIR"]

#The monitor class will hold all run details , it will be the entirety of the program , For Gui I plan to add a gui method 
#We currently have a basic structure in place, but it needs to be expanded with more functionality and edgecases
#such as seeing synced flowdir and pdk as techdir


# a few changes To propose / add are 
# use seras cmd for each run dir rather than one flow directory 
# switch back to threadpool executer 



class Monitor():
    
    def __init__(self):
        self.validWorkSpaces = []
        self.validRuns = []
        self.User = self.getUser()
        # self.getAllRuns()
        self.getWorkSpaces()

    def getUser(self):
        try:
            result = subprocess.run(["printenv", "USER"], text=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            user = result.stdout.strip()
            return user
        except subprocess.CalledProcessError as e:
            print("printenv command failed:", e.stderr.strip())
            exit(1)
                
    def getWorkSpaces(self):
        print("Getting workspaces...")
        workspaceDict = defaultdict(list)
        if not os.path.exists(currentUsers_path):
            print("File not found.")
            exit(1)
        else:
            with open(currentUsers_path, 'r') as file: 
                for line in file:
                    data = json.loads(line)
                    if data["username"] == self.User:
                        try:
                            params_path = os.path.join(data["basedir"], "params.json")
                            with open(params_path, 'r') as params_file:
                                params = json.load(params_file)
                                workspaceDict[params["params"]["FLOW_DIR"]].append(data)
                        except FileNotFoundError:
                            print(f"File not found: {params_path}")
                start_time = time.time()
                with ThreadPoolExecutor() as executor:
                    results = list(executor.map(lambda flow_dir: WorkSpace(self, flow_dir , workspaceDict ), workspaceDict.keys()))
                    self.validWorkSpaces.extend(results) ##FLAG , FLOWDIR ?? 
                print(f"\nFound {len(self.validWorkSpaces)} WorkSpaces found for user: {self.User}\n")
                end_time = time.time()
                elapsed_time = end_time - start_time
                print(f"Time taken to get workspaces: {elapsed_time:.2f} seconds")

    def WriteToJson(self):
        print("Writing to Json")
        with open("tmp_TileBuilderMonitor/tmp.json", 'w') as file:
            for workspace in self.validWorkSpaces:
                for run in workspace.validRuns:
                    if run.validityFlag:
                        file.write(json.dumps(run.dictionary, indent=4))

class WorkSpace():
        def __init__(self, monitor, flow_dir , workspaceDict):
             self.FLOW_DIR = flow_dir
             self.validRuns= self.getRuns(workspaceDict)
             print(f"Initialized WorkSpace for FLOW_DIR: {flow_dir}\n\n")

        def getRuns(self, workspaceDict):
                with ProcessPoolExecutor() as executor:
                    jobs_submitted = [executor.submit(Run, run_dict, self) for run_dict in workspaceDict[self.FLOW_DIR]]
                    return [job.result() for job in as_completed(jobs_submitted)]

        def printRuns(self):
            for run in self.validRuns:
                #print(f"Run: {run.dictionary['basedir']}\n\n")
                print(f"Run: {run.dictionary}\n\n")
  
class Run():
    def __init__(self,json,workSpace):
        self.dictionary = json
        self.validityFlag = True
        self.ACTIVE = False
        self.ERROR = False
        self.getParams()
        self.getTargets()

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

    def getTargets(self):
        self.dictionary["RUNNING_TARGETS"] = []
        self.dictionary["FAILED_TARGETS"] = []
        status_flag = True
        dir = self.dictionary["basedir"].split("/")[-1]
        if "TB_SRV_DIR" in self.dictionary:
            for status in ["RUNNING","FAILED"]:
                cmd = f"""
                source {self.dictionary['TB_SRV_DIR']}/.cshrc; 
                serascmd -find_jobs 'status=={status} dir=~{dir}' -report 'name dir';
                """
                result = subprocess.run(['tcsh', '-c', cmd], text=True, capture_output=True)
                for line in result.stdout.splitlines():
                    if len(line.split()) == 2:
                        ansi_escape = re.compile(
                        r'(?:\x1B[@-_][0-?]*[ -/]*[@-~])'  # ANSI CSI sequences
                        r'|(?:\x1B\][^\x07]*\x07)'         # OSC sequences
                        )
                        # I beleive serascmd is givng me these escape sequences that are visible when Im saving to json
                        # This is only seen after json.dump() , lowkey makes me want to reformat everything and avoid json
                        line = ansi_escape.sub('', line)
                        if status == "RUNNING":
                            self.dictionary["RUNNING_TARGETS"].append(line.split()[0])
                        else:
                            self.dictionary["FAILED_TARGETS"].append(line.split()[0])

        else:
            print(f"TB_SRV_DIR not found in dictionary for: {self.dictionary['basedir']}")



def main():

   TileBuilderMonitor = Monitor()
   TileBuilderMonitor.WriteToJson()    

if __name__ == "__main__":
    main()

# changs to make , get flowdir from p4 rather than json 
# get techno from pdk dir path 
# run faster please 

