import subprocess, sys, time, os

def run(path, args=None):
    cmd = [sys.executable, path] + (args or [])
    return subprocess.Popen(cmd)

if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    procs = []
    # --- launch scripts ---
    procs.append(run(os.path.join(root, "collector_helius.py")))

    procs.append(run(os.path.join(root, "trends.py"), ["run"]))
    procs.append(run(os.path.join(root, "bot.py")))
    procs.append(run(os.path.join(root, "labeler.py")))
    print("collector_dex_new.py, trends.py, bot.py, labeler.py are running.")
    print("Press CTRL+C here to stop all.")
    try:
        while True:
            time.sleep(2)
            for i, p in enumerate(list(procs)):
                if p.poll() is not None:
                    name = ["collector","trends","bot","labeler"][i]
                    print(f"{name} exited; restarting in 5s...")
                    time.sleep(5)
                    # restart the one that died
                    if name=="collector":
                        procs[i]=run(os.path.join(root,"collector_dex_new.py"))
                    elif name=="trends":
                        procs[i]=run(os.path.join(root,"trends.py"),["run"])
                    elif name=="bot":
                        procs[i]=run(os.path.join(root,"bot.py"))
                    elif name=="labeler":
                        procs[i]=run(os.path.join(root,"labeler.py"))
    except KeyboardInterrupt:
        for p in procs:
            try: p.terminate()
            except: pass
        print("Stopped.")
