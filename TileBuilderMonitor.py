#!/usr/bin/env python3.10
 
import subprocess
 
def get_user_with_printenv():
    try:
        result = subprocess.run(["printenv", "USER"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
 
        user = result.stdout.strip()
        return user
    except subprocess.CalledProcessError as e:
        print("printenv command failed:", e.stderr.strip())
        return None
 
if __name__ == "__main__":
    user_from_cmd = get_user_with_printenv()
    print("USER from printenv:", user_from_cmd)