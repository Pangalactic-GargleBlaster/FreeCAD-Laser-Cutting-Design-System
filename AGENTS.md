# FreeCAD files

- A valid shape saved by `FreeCADCmd` can still open with every body hidden: command-line saves omit `GuiDocument.xml`.
- After the **final save** of any `.FCStd` created or modified by command-line FreeCAD, run `python3 tools/set_fcstd_visibility.py path/to/file.FCStd`. It writes visibility for the Part Design bodies and their active Tip features. Do not save the document again with `FreeCADCmd` afterward without repeating this step.
- When saving in FreeCAD's GUI instead, explicitly set each intended body's and active Tip's `ViewObject.Visibility = True` before saving.
- Verify the archive contains `GuiDocument.xml` with `Visibility=true` for the intended bodies and tips. Geometry validation alone does not verify what opens visibly in the GUI.
- Fixture files are baseline inputs. Copy them before modifying them in tests; only overwrite a fixture during an intentional rebuild.
