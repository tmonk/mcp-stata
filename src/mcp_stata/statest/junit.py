from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import TestSuiteSummary

def write_junit_xml(summary: TestSuiteSummary, output_path: str):
    """Serialize TestSuiteSummary to JUnit XML format."""
    root = ET.Element("testsuites")
    
    suite = ET.SubElement(root, "testsuite", {
        "name": "statest",
        "tests": str(summary.total_tests),
        "failures": str(summary.failed),
        "time": f"{sum(r.duration_seconds for r in summary.results):.2f}"
    })
    
    for result in summary.results:
        test_case = ET.SubElement(suite, "testcase", {
            "name": result.test_path,
            "time": f"{result.duration_seconds:.2f}"
        })
        
        if not result.success:
            msg = "Test failed"
            if result.failure:
                f = result.failure
                msg = f"expected {f.expected}, got {f.actual}"
                if f.tolerance:
                    msg += f" (tol={f.tolerance})"
            
            failure = ET.SubElement(test_case, "failure", {
                "message": msg,
                "type": "AssertionError" if result.failure else "RuntimeError"
            })
            
            if result.failure:
                f = result.failure
                failure_text = (
                    f"assertion: {f.command}\n"
                    f"variable:  {f.variable}\n"
                    f"expected:  {f.expected}\n"
                    f"actual:    {f.actual}\n"
                    f"rc:        {result.rc}"
                )
                failure.text = failure_text
            else:
                failure.text = f"rc: {result.rc}"
    
    tree = ET.ElementTree(root)
    # Ensure directory exists
    import os
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    
    with open(output_path, "wb") as f:
        tree.write(f, encoding="utf-8", xml_declaration=True)
