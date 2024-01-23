import os
import time

down_times = 12
up_times = 5

cmd = "python3 pylips.py --host 192.168.178.45 --command "

# TV remote "Options"
os.system(f"{cmd}confirm 1")
# TV remote "Ok"

for i in range(0, down_times):
    # TV remote "Down"
    os.system(f"{cmd}cursor_down 1")
    time.sleep(0.75)

for i in range(0, up_times):
    # TV remote "Up"
    os.system(f"{cmd}cursor_up 1")
    time.sleep(0.75)

# TV remote "Ok"
os.system(f"{cmd}confirm 1")
