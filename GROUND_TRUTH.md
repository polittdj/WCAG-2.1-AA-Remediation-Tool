GROUND TRUTH — EXPECTED AUDITOR RESULTS
These are confirmed by binary inspection. If the auditor disagrees, fix the auditor.

12_0_updated:
  C-18 (Every Widget has StructParent): PASS
  C-33 (Zero non-standard BDC tags):    PASS
  C-34 (Title not placeholder):         PASS
  C-35 (ParentTree is flat /Nums):      PASS

12_0_updated_editable:
  C-18: PASS
  C-33: FAIL  (ExtraCharSpan present)
  C-34: PASS
  C-35: FAIL  (ParentTree is /Kids not flat)

12_0_updated_converted_from_MS_Word:
  C-18: PASS
  C-33: PASS
  C-34: FAIL  (Title is "Untitled Document")
  C-35: PASS

12_0_updated_editable_ADA:
  C-18: PASS
  C-33: FAIL
  C-34: PASS
  C-35: FAIL

CPSSPPC_TRAVEL_FORM:
  C-18: FAIL  (0 of 96 widgets have StructParent)
  C-33: PASS
  C-34: FAIL  (Title is "Untitled Document")
  C-35: PASS
