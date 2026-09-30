import FreeCADGui as Gui

import finger_joint_command  # noqa: F401
import half_lap_command  # noqa: F401


class DesignSystemWorkbench(Gui.Workbench):
    MenuText = "Design System"
    ToolTip = "Tools for laser-cut sheet structures"

    def Initialize(self):
        commands = ["DesignSystem_FingerJoint", "DesignSystem_HalfLap"]
        self.appendToolbar("Design System", commands)
        self.appendMenu("Design System", commands)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(DesignSystemWorkbench())
