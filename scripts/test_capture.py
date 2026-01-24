import stata_setup
stata_setup.config("/Applications/StataNow", "mp")
from pystata import stata
from sfi import Scalar
try:
    stata.run("capture", echo=False)
    print(f"RC after capture: {Scalar.getValue('c(rc)')}")
except Exception as e:
    print(f"Error with capture: {e}")
try:
    stata.run("capture query", echo=False)
    print(f"RC after capture query: {Scalar.getValue('c(rc)')}")
except Exception as e:
    print(f"Error with capture query: {e}")
