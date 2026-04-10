import bpy

class ColorfulConnectionsPreferences(bpy.types.AddonPreferences):
    """插件首选项面板"""
    bl_idname = __package__

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.label(text="此插件现在使用侧边栏面板进行设置")
        col.label(text="请在节点编辑器的工具面板中找到设置")

classes = [
    ColorfulConnectionsPreferences,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)