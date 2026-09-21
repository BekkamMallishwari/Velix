import subprocess
import sys
import time

p = subprocess.Popen(
    [sys.executable, "-m", "velix_agent.main"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

p.stdin.write("My Name is Mallishwari\n")
p.stdin.flush()
time.sleep(1)

p.stdin.write("what is my name\n")
p.stdin.flush()
time.sleep(1)

p.stdin.write("/exit\n")
p.stdin.flush()

stdout, _ = p.communicate()
print(stdout)
