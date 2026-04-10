import bpy
from . import utils

class NODE_OT_select_flow_nodes(bpy.types.Operator):
    """选中当前数据流方向上的所有相关节点"""
    bl_idname = "node.select_flow_nodes"
    bl_label = "选中数据流节点"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.space_data and context.space_data.type == 'NODE_EDITOR' and context.active_node

    def execute(self, context):
        # 获取当前设置
        settings = utils.get_panel_settings()
        direction = settings.get('flow_direction', 'DOWNSTREAM')
        active_node = context.active_node
        
        if not active_node:
            return {'CANCELLED'}
            
        # 使用 utils 中的递归逻辑获取节点集合
        visited_links = set()
        
        if direction == 'BOTH':
            # 双向模式：使用两个独立的 visited_nodes 集合，避免相互干扰
            visited_nodes_forward = set()
            visited_nodes_backward = set()
            
            # 向下遍历
            utils.traverse_recursive(active_node, 'forward', visited_links, visited_nodes_forward)
            # 向上遍历
            utils.traverse_recursive(active_node, 'backward', visited_links, visited_nodes_backward)
            
            # 合并两个方向的节点
            visited_nodes = visited_nodes_forward | visited_nodes_backward
        else:
            # 单向模式：使用一个集合即可
            visited_nodes = set()
            if direction == 'DOWNSTREAM':
                utils.traverse_recursive(active_node, 'forward', visited_links, visited_nodes)
            elif direction == 'UPSTREAM':
                utils.traverse_recursive(active_node, 'backward', visited_links, visited_nodes)
            
        # 执行选择
        # bpy.ops.node.select_all(action='DESELECT') # 可选：是否先取消全选
        for node in visited_nodes:
            node.select = True
            
        return {'FINISHED'}

classes = [
    NODE_OT_select_flow_nodes
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)