#!/usr/bin/env python3.10

# need to edit this shebang here so we can just source this script 

import cmd
from concurrent import futures
import subprocess
import json
from pathlib import Path
import os
import re
import time
from tkinter.tix import STATUS
import tkinter as tk
from tkinter import ttk
from unittest import result
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
 

currentUsers_path = "/tool/aticad/1.0/flow/current_users.json"
os.makedirs("tmp_TileBuilderMonitor",exist_ok=True)

paramsNeeded = ["TECHNO_NAME","FLOW_DIR","TB_SRV_DIR"]
print("this is a test...")
#The monitor class will hold all run details , it will be the entirety of the program , For Gui I plan to add a gui method 
#We currently have a basic structure in place, but it needs to be expanded with more functionality and edgecases
#such as seeing synced flowdir and pdk as techdir
#I also want to organize the initialization
#
#Currently we get ALL runs using the moniter.getAllRuns method and instantiate all our run Objects
#We then find unique workspaces using monitor.getWorkSpaces and create the unique workspaces
#Runs are then mapped to their respective workspaces and then the workspace.getStatus method is called
#
#I would like to move workspace.getStatus to init but I need to figure out a way to get all runs belonging to that workpace
# as or before it is instantiated 
#
#The monitor class will also be responsible for writing the output to a json file for debug / backend 
#
#The workspace.getStatus method is really slow so I've used ProcessPoolExecutor to speed it up from 100 seconds to 40 seconds 

#after the methods that instantiate complete we are left with a monitor object that has all workpsaces and runs 
#runs are  updated and we save them in the validrun attribute within workspaces rather than monitor . I dont like this 
#i would rather create all workspaces first and then create the runs so we dont have two copies of the same list with one outdated . 
#This means i can create all run objects in a workpsace method in its init and then get statuses also in the init of workspace .

class Monitor():
    
    def __init__(self):
        self.validWorkSpaces = []
        self.validRuns = []
        self.User = self.getUser()
        self.getAllRuns()
        self.getWorkSpaces()

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
                
    def getWorkSpaces(self):
        print("Getting workspaces...")
        # Build mapping from FLOW_DIR to WorkSpace
        workspace_map = {}
        unique_flow_dirs = set(run.dictionary["FLOW_DIR"] for run in self.validRuns if "FLOW_DIR" in run.dictionary)
        for flow_dir in unique_flow_dirs:
            workspace_map[flow_dir] = WorkSpace(flow_dir) # creates a map between workspace objects and their flow dir
        # Assign each run to the correct workspace
        for run in self.validRuns:
            flow_dir = run.dictionary.get("FLOW_DIR")
            if flow_dir in workspace_map:
                workspace_map[flow_dir].validRuns.append(run)
            else: 
                print("Anomaly detected: Run with FLOW_DIR not found in workspace map")
                print(f"Run details: {run.dictionary}\n\n")
        self.validWorkSpaces = list(workspace_map.values())

        with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor: # multithreading this thing takes 100s now down to 40s
            future_workspace = {executor.submit(workspace.getStatus): workspace.FLOW_DIR for workspace in self.validWorkSpaces}
            for future in as_completed(future_workspace):
                for workspace in self.validWorkSpaces:
                    if workspace.FLOW_DIR in future_workspace[future]:
                        workspace.validRuns = future.result()

    def WriteToJson(self):
        print("Writing to Json")
        with open("tmp_TileBuilderMonitor/tmp.json", 'w') as file:
            for workspace in self.validWorkSpaces:
                for run in workspace.validRuns:
                    file.write(json.dumps(run.dictionary, indent=4))
    
      # ...existing code...

    def show_gui(self):
        root = tk.Tk()
        root.title("TileBuilderMonitor Workspaces")

        tree = ttk.Treeview(root)
        tree["columns"] = ("Running Targets", "Failed Targets")
        tree.heading("#0", text="FLOW_DIR / Run")
        tree.heading("Running Targets", text="Running Targets")
        tree.heading("Failed Targets", text="Failed Targets")

        for workspace in self.validWorkSpaces:
            ws_id = tree.insert("", "end", text=workspace.FLOW_DIR)
            for run in workspace.validRuns:
                running = ", ".join(run.dictionary.get("RUNNING_TARGETS", []))
                failed = ", ".join(run.dictionary.get("FAILED_TARGETS", []))
                run_name = run.dictionary.get("basedir", "N/A")
                tree.insert(ws_id, "end", text=run_name, values=(running, failed))

        tree.pack(expand=True, fill="both")
        root.mainloop()
# ...existing code...

class WorkSpace():
        def __init__(self, flow_dir):
             self.validRuns=[]
             self.FLOW_DIR = flow_dir
             #print(f"Initialized WorkSpace for FLOW_DIR: {flow_dir}\n\n")

        def printRuns(self):
            for run in self.validRuns:
                print(f"Run: {run.dictionary['basedir']}\n\n")


        def getStatus (self) : # getting status of runs ( failed and running targets)
            print(f"Getting status for FLOW_DIR: {self.FLOW_DIR}")
            run_map = {run.dictionary["basedir"].split("/")[-1]: run for run in self.validRuns if "basedir" in run.dictionary}
            if self.validRuns and self.validRuns[0]: # to clean flag 
                if "TB_SRV_DIR" in self.validRuns[0].dictionary:
                    for status in ["RUNNING", "FAILED", "WAIVED"]:
                        cmd = f"source {self.validRuns[0].dictionary['TB_SRV_DIR']}/.cshrc; serascmd -find_jobs 'status=={status}' -report 'name dir'"
                        result = subprocess.run(['tcsh', '-c', cmd], text=True, capture_output=True)
                        for line in result.stdout.splitlines():
                            # this code is pretty dirty , probably need to clean up 
                            # the output we get looks like : TARGET BASE_DIR
                            # the base dir looks like ../../dir/dir/dir
                            # I want to match the basedir with my rundirs so i need to extract the relevant outputs
                            # and split the line to get the individual parts and i split the basedir to get the part I need 
                            parts = line.strip().split()
                            if len(parts) == 2: # for some reason if line is not the format we are expecting , dont process it . 
                                basedir_split = parts[1].split("/")[-1]
                                target = parts[0]
                                if basedir_split in run_map: # write else statement 
                                    ansi_escape = re.compile(
                                    r'(?:\x1B[@-_][0-?]*[ -/]*[@-~])'  # ANSI CSI sequences
                                    r'|(?:\x1B\][^\x07]*\x07)'         # OSC sequences
                                    )
                                    # I beleive seras cmd is givng me these escape sequences that are visible when Im saving to json
                                    # This is only seen after json.dump() , lowkey makes me want to reformat everything and avoid json
                                    clean_target = ansi_escape.sub('', target)
                                    if status == "RUNNING":
                                        run_map[basedir_split].dictionary["RUNNING_TARGETS"].append(clean_target)
                                        
                                    elif status == "FAILED" or status == "WAIVED":
                                        run_map[basedir_split].dictionary["FAILED_TARGETS"].append(clean_target)
                                        

                    self.validRuns = list(run_map.values())
                    return self.validRuns

                else:
                    print(f"Failed to get status for: {self.FLOW_DIR}")
                    print("TB_SRV_DIR not found in run dictionary, skipping source command")
            else:
                print(f"No valid runs found for FLOW_DIR: {self.FLOW_DIR}")

                 #need to map the run information to the individual runs , specially running targets and failing targets    
class Run():
    def __init__(self,json):
    
        self.dictionary = json
        self.validityFlag = True
        self.ACTIVE = False
        self.ERROR = False
        self.getParams()

    def getParams(self):
        try:
            params_path = os.path.join(self.dictionary["basedir"], "params.json")
            with open(params_path, 'r') as params_file:
                params = json.load(params_file)

                for parameter in paramsNeeded:
                    self.dictionary[parameter] = params["params"][parameter]

                self.dictionary["RUNNING_TARGETS"] = []
                self.dictionary["FAILED_TARGETS"] = []    
        except FileNotFoundError:
            print(f"File not found: {params_path}")
            self.validityFlag = False   

def main():

   TileBuilderMonitor = Monitor()
   TileBuilderMonitor.WriteToJson()
   TileBuilderMonitor.show_gui()
   
if __name__ == "__main__":
    main()

# changs to make , get flowdir from p4 rather than json 
# get techno from pdk dir path 
# run faster please 

