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


paramsNeeded = ["TECHNO_NAME","FLOW_DIR","TB_SRV_DIR","FC_MODULE"]

Verbose = False # for ERRORS and debugging

#The monitor class will hold all run details , it will be the entirety of the program , For Gui I plan to add a gui method 
#We currently have a basic structure in place, but it needs to be expanded with more functionality and edgecases
#such as seeing synced flowdir and pdk as techdir

# a few changes To propose / add are
# use seras cmd for each run dir rather than one flow directory
# switch back to threadpool executor



class Monitor():
    
    def __init__(self):
        self.validWorkSpaces = []
        self.validRuns = []
        self.currentUser = self.getUser()
        self.inputs = self.getInput()
        self.usersToMonitor , self.runsToMonitor = self.getToMonitor()
        self.getWorkSpaces()


    @staticmethod
    def getUser():
        try:
            result = subprocess.run(["printenv", "USER"], text=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            user = result.stdout.strip()
            return user
        except subprocess.CalledProcessError as e:
            print("printenv command failed:", e.stderr.strip())
            exit(1)

    def getInput(self):
        with open(f"tmp_TileBuilderMonitor/{self.currentUser}/inputs.json", 'r') as file:
            return json.load(file)

    def getToMonitor(self):
        users = []
        runs = []
        if self.inputs.get("user", None):
            print(f"Monitoring for user: {self.inputs['user']}")
            users = self.inputs['user'].split(",")
        else:
            print("Monitoring Current user Only")
            users.append(self.currentUser)

        if self.inputs.get("run_dir", None):
            with open(self.inputs['run_dir'], 'r') as file:
                for line in file:

                    runs.append(line.strip())
        else:
            print("Monitoring runs for Current user")

        return users , runs    
                
    def getWorkSpaces(self):
        print("Getting workspaces...")
        workspaceDict = defaultdict(list)   # Needed this to get be able to add keys that dont exist yet , not sure why but it was a COPILOT Fix
        if not os.path.exists(currentUsers_path):
            print("File not found.")
            exit(1)
        else:
            with open(currentUsers_path, 'r') as file: 
                for line in file:
                    data = json.loads(line)
                    if data["username"] in self.usersToMonitor or data["basedir"] in self.runsToMonitor:  # only get workspaces for users we care about
                        try:
                            params_path = os.path.join(data["basedir"], "params.json")
                            with open(params_path, 'r') as params_file:
                                params = json.load(params_file)
                                workspaceDict[params["params"]["FLOW_DIR"]].append(data)   # adding the json object of the run to the list of that flowdir
                        except FileNotFoundError:
                            print(f"File not found: {params_path}")
                        except PermissionError as e:
                            print(f"PermissionError: {e} while accessing {params_path}")

                start_time = time.time()
                with ThreadPoolExecutor() as executor:
                    results = list(executor.map(lambda flow_dir: WorkSpace(self, flow_dir , workspaceDict ), workspaceDict.keys()))  # this is where we create the workspace objects , one for each flowdir
                    #FLAG , Maybe don't send in the whole dict , just the list of runs for that flowdir , workspaceDict[flow_dir] rather than worksapceDict 
                    self.validWorkSpaces.extend(results) # add all the workspace objects to the monitor object
                print(f"\nFound {len(self.validWorkSpaces)} WorkSpaces found for user: {self.currentUser}\n")
                end_time = time.time()
                elapsed_time = end_time - start_time
                print(f"Time taken to get workspaces: {elapsed_time:.2f} seconds") #everything done to create workspaces and runs in the worksspace is done in the init so I'm timing the creation of all objects

    def WriteToJson(self):
        print("Writing to Json")
        os.makedirs(f"tmp_TileBuilderMonitor/{self.currentUser}", exist_ok=True)
        with open(f"tmp_TileBuilderMonitor/{self.currentUser}/tmp.json", 'w') as file:
            for workspace in self.validWorkSpaces:
                for run in workspace.validRuns:
                    if run.validityFlag:
                        file.write(json.dumps(run.dictionary, indent=4))
                                   
class WorkSpace():
    def __init__(self, monitor, flow_dir , workspaceDict):
            self.FLOW_DIR = flow_dir
            self.inputs = monitor.inputs
            self.validRuns= self.getRuns(workspaceDict)
            self.getStatus()
            if self.inputs.get("qor", False):  # Check if 'qor' key exists and is True
                self.getQoRSummary()
            print(f"Initialized WorkSpace for FLOW_DIR: {flow_dir}\n\n")

    def getRuns(self, workspaceDict):
            with ThreadPoolExecutor() as executor:
                jobs_submitted = [executor.submit(Run, run_dict, self) for run_dict in workspaceDict[self.FLOW_DIR]] # create a Run object for each run in the workspace based on how many json objects we have for that flowdir
                return [job.result() for job in as_completed(jobs_submitted)]

    def printRuns(self):
        for run in self.validRuns:
            print(f"Run: {run.dictionary}\n\n")

    def getStatus(self):

        run_map = {run.dictionary["basedir"].split("/")[-1]:run for run in self.validRuns if "basedir" in run.dictionary}  # map of basedir to run object for easy access to map targets to the correct run object in seras cmd output , output looks like
                                                                                                                            # TargetName ../../basedir , Alot faster to map the targets to runs than using the command for every run object 
            
        if "TB_SRV_DIR" in self.validRuns[0].dictionary:
            for status in ["RUNNING","FAILED"]: # Sources enviornmental variables for that flowdir and spits out all jobs with that status in that workspace
                cmd = f"""
                source {self.validRuns[0].dictionary['TB_SRV_DIR']}/.cshrc;   
                serascmd -find_jobs 'status=={status} ' -report 'name dir';
                """
                result = subprocess.run(['tcsh', '-c', cmd], text=True, capture_output=True)
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) == 2:
                        Target = parts[0]
                        base_dir = parts[1].split("/")[-1]

                        ansi_escape = re.compile(
                        r'(?:\x1B[@-_][0-?]*[ -/]*[@-~])'  # ANSI CSI sequences
                        r'|(?:\x1B\][^\x07]*\x07)'         # OSC sequences
                        )
                        # I beleive serascmd is givng me these escape sequences that are visible when Im saving to json
                        # This is only seen after json.dump() , lowkey makes me want to reformat everything and avoid json
                        Target = ansi_escape.sub('', Target)
                        
                        try:
                            if status == "RUNNING":
                                run_map[base_dir].dictionary["RUNNING_TARGETS"].append(Target)
                            else:
                                run_map[base_dir].dictionary["FAILED_TARGETS"].append(Target)
                        except KeyError:
                            if Verbose:
                                print(f"KeyError: {base_dir} not found in run_map")  # Runs that don't share the same flowdir are sometimes technically in the same workspace , for example if we use --newflow when branching 
                                print(f"Available keys: {list(run_map.keys())}") # these runs will show up when using seras cmd for that workspace , but we dont have them in our run_map as theya re different flowdirs so this causes a keyerror
                            continue


            self.validRuns = list(run_map.values())
            return self.validRuns

        else:
            print(f"TB_SRV_DIR not found in dictionary for: {self.dictionary['basedir']}")

    def getQoRSummary(self):
                         
        futures = []
        processes = []
        
        tile_map = defaultdict(list)  # map of tile to run object for easy access when doing qor summary
        for run in self.validRuns:
            tile_map[run.dictionary["tilename"]].append(run)  # assuming tilename is a key in the run dictionary

        for tile in tile_map.values():
            location_list = []
            names_str = ""
            fc_module = tile[0].dictionary["FC_MODULE"]
            for run in tile:
                output = f"tmp_TileBuilderMonitor/{tile[0].dictionary['label']}/{tile[0].dictionary['tilename']}"
                full_path = os.path.abspath(os.path.join( output , 'index.html'))
                try:
                    if not os.path.isdir(os.path.join(os.path.abspath(run.dictionary["basedir"]), "data","PlaceQorData")):
                        if not os.path.isdir(os.path.join(os.path.abspath(run.dictionary["basedir"]), "data","PrePlaceQorData")):
                            if not os.path.isdir(os.path.join(os.path.abspath(run.dictionary["basedir"]), "data","SynthesizeQorData")):
                                    print(f"Could not find QOR data for {run.dictionary['nickname']} in {run.dictionary['basedir']}")
                                    continue
                            else :
                                location_list.append(os.path.join(os.path.abspath(run.dictionary["basedir"]), "data", "SynthesizeQorData"))
                        else :
                            location_list.append(os.path.join(os.path.abspath(run.dictionary["basedir"]), "data", "PrePlaceQorData"))
                    else :
                        location_list.append(os.path.join(os.path.abspath(run.dictionary["basedir"]), "data", "PlaceQorData"))

                    names_str += f"{run.dictionary['nickname']} "         
                except Exception as e:
                    print(f"Error occurred while processing run {run.dictionary['nickname']}: {e}")

                run.dictionary["link"] = f"https://logviewer-atl.amd.com{full_path}"    
            locations_str = " ".join([location for location in location_list])
            command = f'compare_qor_data -force -run_locations "{locations_str}" -run_names "{names_str}" -output {output}; exit'

        #     processes.append(subprocess.Popen(["tcsh", "-c", f"module load {fc_module}; fc_shell -x '{command}'"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        # for process in processes:
        #     try:
        #         stdout, stderr = process.communicate()
        #         if process.returncode == 0:
        #             # if Verbose:
        #             print(f"Process completed successfully:\n{stdout}\n")
        #         else:
        #             print(f"Process failed with return code {process.returncode}:\n{stderr}\n")
        #     except Exception as e:
        #         print(f"Error occurred while waiting for process: {e}")     

                     

            with ProcessPoolExecutor() as executor:
                futures.append(executor.submit(subprocess.run, ["tcsh", "-c", f"module load {fc_module}; fc_shell -x '{command}'"], text=True, capture_output=True))

        for future in futures:
            try:
                result = future.result()
            except Exception as e:
                print(f"Error occurred: {e}")


       

  
class Run():
    def __init__(self,json,workSpace):
        self.dictionary = json
        self.validityFlag = True
        self.ACTIVE = False
        self.ERROR = False
        self.getParams()
        self.dictionary["RUNNING_TARGETS"] = []
        self.dictionary["FAILED_TARGETS"] = []
        self.dictionary["link"] = []

    def getParams(self):
        try:
            params_path = os.path.join(self.dictionary["basedir"], "params.json")
            
            with open(params_path, 'r') as params_file:   # load params.json and get needed parameters 
                params = json.load(params_file)
                for parameter in paramsNeeded:
                    self.dictionary[parameter] = params["params"][parameter] # tounge twiser might change 

    
        except FileNotFoundError:
            print(f"File not found: {params_path}")
            self.validityFlag = False   



def main():

   TileBuilderMonitor = Monitor()
   TileBuilderMonitor.WriteToJson()    

if __name__ == "__main__":
    main()

# changs to make , get flowdir from p4 rather than json 
# get techno from pdk dir path 
# run faster please 

