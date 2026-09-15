import FreeCADGui as Gui

import finger_joint_command  # noqa: F401


class DesignSystemWorkbench(Gui.Workbench):
    MenuText = "Design System"
    ToolTip = "Tools for laser-cut sheet structures"

    def Initialize(self):
        self.appendToolbar("Design System", ["DesignSystem_FingerJoint"])
        self.appendMenu("Design System", ["DesignSystem_FingerJoint"])

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(DesignSystemWorkbench())
