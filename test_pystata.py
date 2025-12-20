import stata_setup
stata_setup.config("/Applications/StataNow/", "mp")
from pystata import stata

def bench():    # warm-up
    stata.run('sysuse auto, clear')
    stata.run('graph twoway scatter mpg weight')
    


    

if __name__ == "__main__":
    import json
    results = bench()
    print(json.dumps(results, indent=2))
