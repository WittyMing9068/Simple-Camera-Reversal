# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

"""
彩色连线插件
描述: 为Blender节点编辑器提供彩色连线功能
"""

import bpy
from . import preferences
from . import panels
from . import operators
from . import utils

bl_info = {
    "name": "彩色连线",
    "author": "Blender超级技术交流社",
    "version": (1, 1, 2),
    "blender": (4, 2, 0),
    "location": "节点编辑器 > 侧边栏",
    "description": "为Blender节点编辑器提供彩色连线功能，增强节点编辑体验",
    "warning": "",
    "doc_url": "",
    "category": "Node",
}

def register():
    preferences.register()
    panels.register()
    operators.register()
    utils.register()
    print("已注册")
def unregister():
    utils.unregister()
    operators.unregister()
    panels.unregister()
    preferences.unregister()
    print("已注销")
if __name__ == "__main__":
    register()