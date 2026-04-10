import bpy
import json
import os

# 全局变量初始化
_loading_settings = False
_AUTOSAVE_DELAY = 0.25
_pending_save_settings = None
_autosave_timer_registered = False


def _safe_get_scene(prefer_context=True):
    scene = None
    if prefer_context:
        try:
            if hasattr(bpy, 'context') and hasattr(bpy.context, 'scene'):
                scene = bpy.context.scene
        except Exception:
            scene = None

    if scene and hasattr(scene, 'colorful_connections_settings'):
        return scene

    try:
        if hasattr(bpy, 'data') and hasattr(bpy.data, 'scenes') and bpy.data.scenes:
            for candidate in bpy.data.scenes:
                if hasattr(candidate, 'colorful_connections_settings'):
                    return candidate
    except Exception:
        pass
    return None


def _ensure_default_gradient_colors(settings):
    try:
        if len(settings.gradient_colors) == 0:
            settings.gradient_color_count = 5
            settings._update_color_count()
    except (AttributeError, RuntimeError, ReferenceError) as e:
        print(f"设置gradient_color_count失败: {e}")

    try:
        if len(settings.field_gradient_colors) == 0:
            settings.field_gradient_color_count = 5
            settings._update_field_color_count()
    except (AttributeError, RuntimeError, ReferenceError) as e:
        print(f"设置field_gradient_color_count失败: {e}")

    try:
        if len(settings.endpoint_gradient_colors) == 0:
            settings.endpoint_gradient_color_count = 5
            settings._update_endpoint_color_count()
    except (AttributeError, RuntimeError, ReferenceError) as e:
        print(f"设置endpoint_gradient_color_count失败: {e}")


def _apply_initial_preset_if_needed(settings):
    try:
        if len(settings.gradient_presets) == 0 or len(settings.gradient_colors) != 0:
            return

        preset_to_apply = None
        preset_index_to_use = -1

        last_applied = getattr(settings, 'last_applied_preset_index', -1)
        if last_applied >= 0 and last_applied < len(settings.gradient_presets):
            preset_index_to_use = last_applied
            preset_to_apply = settings.gradient_presets[last_applied]
            settings.active_preset_index = last_applied
        elif settings.active_preset_index >= 0 and settings.active_preset_index < len(settings.gradient_presets):
            preset_index_to_use = settings.active_preset_index
            preset_to_apply = settings.gradient_presets[settings.active_preset_index]
        else:
            preset_index_to_use = 0
            preset_to_apply = settings.gradient_presets[0]
            settings.active_preset_index = 0

        if not preset_to_apply:
            return

        settings.gradient_colors.clear()
        for preset_color in preset_to_apply.colors:
            new_color = settings.gradient_colors.add()
            new_color.color = preset_color.color[:]
            new_color.alpha = getattr(preset_color, 'alpha', 1.0)
        settings.gradient_color_count = len(preset_to_apply.colors)
        settings.active_preset_index = preset_index_to_use
        settings.last_applied_preset_index = preset_index_to_use
        print(f"已自动应用预设: {preset_to_apply.name} (索引: {preset_index_to_use})")
    except (AttributeError, RuntimeError, ReferenceError) as e:
        print(f"处理预设失败: {e}")
    except Exception as e:
        print(f"自动应用预设失败: {e}")
        import traceback
        traceback.print_exc()


def _initialize_scene_settings(scene=None):
    if scene is None:
        scene = _safe_get_scene()
    if not scene or not hasattr(scene, 'colorful_connections_settings'):
        return False

    try:
        _ = scene.name
        settings = scene.colorful_connections_settings
    except (AttributeError, RuntimeError, ReferenceError) as e:
        print(f"场景不可访问: {e}")
        return False

    try:
        load_presets_from_file(settings)
    except Exception as e:
        print(f"加载预设失败: {e}")
        import traceback
        traceback.print_exc()

    try:
        load_global_settings(settings)
    except Exception as e:
        print(f"加载全局设置失败: {e}")
        import traceback
        traceback.print_exc()

    _ensure_default_gradient_colors(settings)
    _apply_initial_preset_if_needed(settings)
    return True

# 获取全局设置文件路径
def get_settings_filepath():
    """获取全局设置JSON文件的路径（保存在插件目录）"""
    try:
        # 方法1：通过 __file__ 获取当前模块路径（最可靠）
        current_dir = os.path.dirname(os.path.abspath(__file__))
        addon_dir = os.path.dirname(current_dir) if os.path.basename(current_dir) != 'colorful_connections' else current_dir
        
        # 确保在插件目录中
        if os.path.basename(addon_dir) == 'colorful_connections':
            settings_dir = os.path.join(addon_dir, 'presets')
        else:
            settings_dir = os.path.join(current_dir, 'presets')
        
        os.makedirs(settings_dir, exist_ok=True)
        return os.path.join(settings_dir, 'global_settings.json')
        
    except Exception as e:
        # 备用方案：通过 addon preferences 获取
        try:
            addon_name = 'colorful_connections'
            if hasattr(bpy.context, 'preferences'):
                addon_prefs = bpy.context.preferences.addons.get(addon_name)
                if addon_prefs and hasattr(addon_prefs, 'module') and hasattr(addon_prefs.module, '__file__'):
                    prefs_dir = os.path.dirname(addon_prefs.module.__file__)
                    settings_dir = os.path.join(prefs_dir, 'presets')
                    os.makedirs(settings_dir, exist_ok=True)
                    return os.path.join(settings_dir, 'global_settings.json')
        except:
            pass
        
        # 最后的备用方案：使用用户配置目录
        try:
            config_dir = bpy.utils.user_resource('CONFIG')
            settings_dir = os.path.join(config_dir, 'addons', 'colorful_connections', 'presets')
            os.makedirs(settings_dir, exist_ok=True)
            return os.path.join(settings_dir, 'global_settings.json')
        except:
            # 最终备用：使用临时目录
            import tempfile
            temp_dir = tempfile.gettempdir()
            settings_dir = os.path.join(temp_dir, 'colorful_connections_settings')
            os.makedirs(settings_dir, exist_ok=True)
            return os.path.join(settings_dir, 'global_settings.json')

# 获取预设文件路径
def get_presets_filepath():
    """获取预设JSON文件的路径（保存在插件目录）"""
    try:
        # 方法1：通过 __file__ 获取当前模块路径（最可靠）
        # 获取 panels.py 的目录，然后向上找到插件根目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        addon_dir = os.path.dirname(current_dir) if os.path.basename(current_dir) != 'colorful_connections' else current_dir
        
        # 确保在插件目录中
        if os.path.basename(addon_dir) == 'colorful_connections':
            presets_dir = os.path.join(addon_dir, 'presets')
        else:
            presets_dir = os.path.join(current_dir, 'presets')
        
        os.makedirs(presets_dir, exist_ok=True)
        filepath = os.path.join(presets_dir, 'gradient_presets.json')
        return filepath
        
    except Exception as e:
        # 备用方案：通过 addon preferences 获取
        try:
            addon_name = 'colorful_connections'
            if hasattr(bpy.context, 'preferences'):
                addon_prefs = bpy.context.preferences.addons.get(addon_name)
                if addon_prefs and hasattr(addon_prefs, 'module') and hasattr(addon_prefs.module, '__file__'):
                    prefs_dir = os.path.dirname(addon_prefs.module.__file__)
                    presets_dir = os.path.join(prefs_dir, 'presets')
                    os.makedirs(presets_dir, exist_ok=True)
                    return os.path.join(presets_dir, 'gradient_presets.json')
        except:
            pass
        
        # 最后的备用方案：使用用户配置目录
        try:
            config_dir = bpy.utils.user_resource('CONFIG')
            presets_dir = os.path.join(config_dir, 'addons', 'colorful_connections', 'presets')
            os.makedirs(presets_dir, exist_ok=True)
            return os.path.join(presets_dir, 'gradient_presets.json')
        except:
            # 最终备用：使用临时目录
            import tempfile
            temp_dir = tempfile.gettempdir()
            presets_dir = os.path.join(temp_dir, 'colorful_connections_presets')
            os.makedirs(presets_dir, exist_ok=True)
            return os.path.join(presets_dir, 'gradient_presets.json')

# 保存预设到文件
def save_presets_to_file(settings):
    """将预设保存到JSON文件"""
    try:
        presets_data = []
        for preset in settings.gradient_presets:
            preset_data = {
                'name': preset.name,
                'colors': []
            }
            for color_item in preset.colors:
                preset_data['colors'].append({
                    'color': list(color_item.color[:3]),  # RGB
                    'alpha': getattr(color_item, 'alpha', 1.0)  # 透明度
                })
            presets_data.append(preset_data)
        
        filepath = get_presets_filepath()
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(presets_data, f, ensure_ascii=False, indent=2)
        
        print(f"预设已保存到: {filepath}")
    except Exception as e:
        print(f"保存预设失败: {e}")
        import traceback
        traceback.print_exc()

# 保存全局设置到文件（仅用于手动保存）
def _save_global_settings_internal(settings):
    """内部保存函数（仅用于手动保存）"""
    try:
        settings_data = {
            # 追踪模式设置
            'trace_mode': settings.trace_mode,
            'flow_direction': settings.flow_direction,
            'lock_flow': settings.lock_flow,

            # 颜色设置
            'enable_type_based_colors': settings.enable_type_based_colors,
            'connection_color_type': settings.connection_color_type,
            'gradient_color_count': settings.gradient_color_count,
            'gradient_colors': [],
            'field_gradient_color_count': getattr(settings, 'field_gradient_color_count', 5),
            'field_gradient_colors': [],
            'endpoint_gradient_color_count': getattr(settings, 'endpoint_gradient_color_count', 5),
            'endpoint_gradient_colors': [],

            # 外观设置
            'animation_speed': settings.animation_speed,
            'line_thickness': settings.line_thickness,
            'node_border_thickness': settings.node_border_thickness,
            'endpoint_overlay_size': getattr(settings, 'endpoint_overlay_size', 1.0),
            'endpoint_overlay_thickness': getattr(settings, 'endpoint_overlay_thickness', 0.78),
            'enable_colorful_connections': settings.enable_colorful_connections,
            'overall_opacity': getattr(settings, 'overall_opacity', 1.0),
            'backing_color_rgb': list(getattr(settings, 'backing_color_rgb', (0.0, 0.0, 0.0))),
            'backing_color_alpha': getattr(settings, 'backing_color_alpha', 0.55),

            # 预设相关
            'active_preset_index': settings.active_preset_index,
            'last_applied_preset_index': getattr(settings, 'last_applied_preset_index', -1),
        }
        
        # 保存当前颜色配置（Constant）
        for color_item in settings.gradient_colors:
            settings_data['gradient_colors'].append({
                'color': list(color_item.color[:3]),
                'alpha': getattr(color_item, 'alpha', 1.0)
            })
        
        # 保存Field颜色配置
        for color_item in getattr(settings, 'field_gradient_colors', []):
            settings_data['field_gradient_colors'].append({
                'color': list(color_item.color[:3]),
                'alpha': getattr(color_item, 'alpha', 1.0)
            })

        # 保存端点空心罩颜色配置
        for color_item in getattr(settings, 'endpoint_gradient_colors', []):
            settings_data['endpoint_gradient_colors'].append({
                'color': list(color_item.color[:3]),
                'alpha': getattr(color_item, 'alpha', 1.0)
            })
        
        filepath = get_settings_filepath()
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(settings_data, f, ensure_ascii=False, indent=2)
        
        print(f"全局设置已保存到: {filepath}")
    except Exception as e:
        print(f"保存全局设置失败: {e}")
        import traceback
        traceback.print_exc()

# 从文件加载全局设置
def load_global_settings(settings):
    """从JSON文件加载全局设置（安全版本，检查上下文可写性）"""
    global _loading_settings, _pending_save_settings
    
    # 检查 settings 是否有效
    if not settings:
        return
    
    # 尝试访问 settings 的属性来检查是否可写
    try:
        _ = settings.connection_color_type
    except (AttributeError, RuntimeError, ReferenceError):
        print("警告: 无法访问设置，跳过加载")
        return
    
    _loading_settings = True
    try:
        filepath = get_settings_filepath()
        if not os.path.exists(filepath):
            print(f"全局设置文件不存在: {filepath}")
            return
        
        with open(filepath, 'r', encoding='utf-8') as f:
            settings_data = json.load(f)
        
        if not settings_data:
            return
        
        # 加载追踪模式设置
        if 'trace_mode' in settings_data:
            settings.trace_mode = settings_data['trace_mode']
        if 'flow_direction' in settings_data:
            settings.flow_direction = settings_data['flow_direction']
        if 'lock_flow' in settings_data:
            settings.lock_flow = settings_data['lock_flow']
        
        # 加载颜色设置
        if 'enable_type_based_colors' in settings_data:
            settings.enable_type_based_colors = settings_data['enable_type_based_colors']
        if 'connection_color_type' in settings_data:
            # 兼容旧数据：如果是RAINBOW，改为CUSTOM
            color_type = settings_data['connection_color_type']
            settings.connection_color_type = 'CUSTOM' if color_type == 'RAINBOW' else color_type
        if 'gradient_color_count' in settings_data:
            settings.gradient_color_count = settings_data['gradient_color_count']
        
        # 加载颜色列表（Constant）
        if 'gradient_colors' in settings_data:
            try:
                settings.gradient_colors.clear()
                for color_data in settings_data['gradient_colors']:
                    color_item = settings.gradient_colors.add()
                    color_rgb = color_data.get('color', [1.0, 1.0, 1.0])
                    color_item.color = (color_rgb[0], color_rgb[1], color_rgb[2])
                    color_item.alpha = color_data.get('alpha', 1.0)
            except Exception as e:
                print(f"加载Constant颜色列表失败: {e}")
                # 如果失败，尝试使用更新颜色数量的方式来初始化
                try:
                    if 'gradient_color_count' in settings_data:
                        settings.gradient_color_count = settings_data['gradient_color_count']
                except:
                    pass
        
        # 加载Field颜色列表
        if 'field_gradient_color_count' in settings_data:
            settings.field_gradient_color_count = settings_data['field_gradient_color_count']
        if 'field_gradient_colors' in settings_data:
            try:
                settings.field_gradient_colors.clear()
                for color_data in settings_data['field_gradient_colors']:
                    color_item = settings.field_gradient_colors.add()
                    color_rgb = color_data.get('color', [0.8, 0.2, 1.0])
                    color_item.color = (color_rgb[0], color_rgb[1], color_rgb[2])
                    color_item.alpha = color_data.get('alpha', 1.0)
            except Exception as e:
                print(f"加载Field颜色列表失败: {e}")
                # 如果失败，尝试使用更新颜色数量的方式来初始化
                try:
                    if 'field_gradient_color_count' in settings_data:
                        settings.field_gradient_color_count = settings_data['field_gradient_color_count']
                except:
                    pass

        # 加载端点空心罩颜色列表
        if 'endpoint_gradient_color_count' in settings_data:
            settings.endpoint_gradient_color_count = settings_data['endpoint_gradient_color_count']
        if 'endpoint_gradient_colors' in settings_data:
            try:
                settings.endpoint_gradient_colors.clear()
                for color_data in settings_data['endpoint_gradient_colors']:
                    color_item = settings.endpoint_gradient_colors.add()
                    color_rgb = color_data.get('color', [0.0, 0.5, 1.0])
                    color_item.color = (color_rgb[0], color_rgb[1], color_rgb[2])
                    color_item.alpha = color_data.get('alpha', 1.0)
            except Exception as e:
                print(f"加载端点空心罩颜色列表失败: {e}")
                try:
                    if 'endpoint_gradient_color_count' in settings_data:
                        settings.endpoint_gradient_color_count = settings_data['endpoint_gradient_color_count']
                except:
                    pass
        
        # 加载外观设置
        if 'animation_speed' in settings_data:
            settings.animation_speed = settings_data['animation_speed']
        if 'line_thickness' in settings_data:
            settings.line_thickness = settings_data['line_thickness']
        if 'node_border_thickness' in settings_data:
            settings.node_border_thickness = settings_data['node_border_thickness']
        if 'endpoint_overlay_size' in settings_data:
            settings.endpoint_overlay_size = settings_data['endpoint_overlay_size']
        if 'endpoint_overlay_thickness' in settings_data:
            settings.endpoint_overlay_thickness = settings_data['endpoint_overlay_thickness']
        if 'enable_colorful_connections' in settings_data:
            settings.enable_colorful_connections = settings_data['enable_colorful_connections']
        if 'overall_opacity' in settings_data:
            settings.overall_opacity = settings_data['overall_opacity']
        # 加载底层背景颜色（兼容新旧格式）
        if 'backing_color' in settings_data:
            # 旧格式：RGBA向量
            backing_color_data = settings_data['backing_color']
            if isinstance(backing_color_data, (list, tuple)):
                if len(backing_color_data) >= 4:
                    settings.backing_color_rgb = tuple(backing_color_data[:3])
                    settings.backing_color_alpha = float(backing_color_data[3])
                elif len(backing_color_data) == 3:
                    settings.backing_color_rgb = tuple(backing_color_data[:3])
                    settings.backing_color_alpha = 0.55
                else:
                    settings.backing_color_rgb = (0.0, 0.0, 0.0)
                    settings.backing_color_alpha = 0.55
        elif 'backing_color_rgb' in settings_data:
            # 新格式：RGB和Alpha分开
            rgb_data = settings_data.get('backing_color_rgb', [0.0, 0.0, 0.0])
            if isinstance(rgb_data, (list, tuple)) and len(rgb_data) >= 3:
                settings.backing_color_rgb = tuple(rgb_data[:3])
            else:
                settings.backing_color_rgb = (0.0, 0.0, 0.0)
            settings.backing_color_alpha = settings_data.get('backing_color_alpha', 0.55)
        
        # 加载预设索引
        if 'active_preset_index' in settings_data:
            settings.active_preset_index = settings_data['active_preset_index']
        if 'last_applied_preset_index' in settings_data:
            settings.last_applied_preset_index = settings_data['last_applied_preset_index']
        
        print(f"已加载全局设置从: {filepath}")
    except Exception as e:
        print(f"加载全局设置失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _loading_settings = False
        _pending_save_settings = None

# 从文件加载预设
def load_presets_from_file(settings):
    """从JSON文件加载预设（安全版本）"""
    # 检查 settings 是否有效
    if not settings:
        return
    
    try:
        # 检查 settings 是否可访问
        _ = settings.gradient_presets
    except (AttributeError, RuntimeError, ReferenceError):
        print("警告: 无法访问预设设置，跳过加载")
        return
    
    try:
        filepath = get_presets_filepath()
        if not os.path.exists(filepath):
            print(f"预设文件不存在: {filepath}")
            return
        
        with open(filepath, 'r', encoding='utf-8') as f:
            presets_data = json.load(f)
        
        if not presets_data:
            return
        
        # 清空现有预设
        settings.gradient_presets.clear()
        
        # 加载预设
        for preset_data in presets_data:
            preset = settings.gradient_presets.add()
            preset.name = preset_data.get('name', '新预设')
            
            for color_data in preset_data.get('colors', []):
                color_item = preset.colors.add()
                color_rgb = color_data.get('color', [1.0, 1.0, 1.0])
                color_item.color = (color_rgb[0], color_rgb[1], color_rgb[2])
                color_item.alpha = color_data.get('alpha', 1.0)
        
        # 设置活动索引
        if len(settings.gradient_presets) > 0:
            settings.active_preset_index = 0
        
        print(f"已加载 {len(settings.gradient_presets)} 个预设从: {filepath}")
    except Exception as e:
        print(f"加载预设失败: {e}")
        import traceback
        traceback.print_exc()

# UI列表显示预设
class UI_UL_gradient_preset_list(bpy.types.UIList):
    """预设列表UI"""
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.name, icon='PRESET')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='PRESET')

# 辅助函数：自动保存当前设置

def _get_settings_from_context(context=None):
    try:
        ctx = context or bpy.context
        scene = getattr(ctx, 'scene', None)
        if scene and hasattr(scene, 'colorful_connections_settings'):
            return scene.colorful_connections_settings
    except Exception:
        pass
    return None


def _flush_pending_settings_save():
    global _pending_save_settings, _autosave_timer_registered
    _autosave_timer_registered = False

    if _loading_settings:
        return None

    settings = _pending_save_settings
    _pending_save_settings = None
    if settings is None:
        return None

    try:
        _ = settings.enable_colorful_connections
    except (AttributeError, RuntimeError, ReferenceError):
        return None

    _save_global_settings_internal(settings)
    return None

def _autosave_settings(context=None):
    global _loading_settings, _pending_save_settings, _autosave_timer_registered
    if _loading_settings:
        return

    settings = _get_settings_from_context(context)
    if settings is None:
        return

    _pending_save_settings = settings
    if _autosave_timer_registered:
        return

    bpy.app.timers.register(_flush_pending_settings_save, first_interval=_AUTOSAVE_DELAY)
    _autosave_timer_registered = True


def _gradient_color_update(self, context):
    """颜色更新时的回调"""
    _force_redraw_update()
    _autosave_settings(context)


def _save_and_redraw_update(self, context):
    _force_redraw_update()
    _autosave_settings(context)

def _force_redraw_update():
    """当底层背景颜色改变时，强制触发重绘"""
    try:
        for wm in bpy.data.window_managers:
            for window in wm.windows:
                for area in window.screen.areas:
                    if area.type == 'NODE_EDITOR':
                        area.tag_redraw()
    except Exception:
        pass  # 如果context不可用，忽略错误

# 预设方案数据结构
class GradientColorItem(bpy.types.PropertyGroup):
    """单个渐变颜色项"""
    color: bpy.props.FloatVectorProperty(
        name="颜色",
        subtype='COLOR',
        default=(1.0, 1.0, 1.0),
        min=0.0, max=1.0,
        size=3,  # RGB only
        update=_gradient_color_update
    )
    alpha: bpy.props.FloatProperty(
        name="透明度",
        description="该颜色的透明度（0.0=完全透明，1.0=完全不透明）",
        default=1.0,
        min=0.0,
        max=1.0,
        update=_gradient_color_update
    )

class GradientPreset(bpy.types.PropertyGroup):
    """渐变预设方案"""
    name: bpy.props.StringProperty(name="预设名称", default="新预设")
    colors: bpy.props.CollectionProperty(type=GradientColorItem)
    active_color_index: bpy.props.IntProperty(default=0)

class ColorfulConnectionsSettings(bpy.types.PropertyGroup):
    """彩色连线设置"""
    
    # --- 追踪模式设置 ---
    trace_mode: bpy.props.EnumProperty(
        name="追踪模式",
        description="选择连线显示的逻辑",
        items=[
            ('ALL_SELECTED', '所有选中', '显示所有被选中节点的连线'),
            ('ACTIVE_FLOW', '活动节点流', '仅显示当前活动节点的数据流向'),
        ],
        default='ACTIVE_FLOW',
        update=_save_and_redraw_update
    )
    
    flow_direction: bpy.props.EnumProperty(
        name="流向",
        description="数据流追踪的方向",
        items=[
            ('BOTH', '双向', '显示输入来源和输出去向'),
            ('UPSTREAM', '向上追溯 (输入)', '仅显示数据的来源'),
            ('DOWNSTREAM', '向下传递 (输出)', '仅显示数据被哪里使用了'),
        ],
        default='BOTH',
        update=_save_and_redraw_update
    )
    
    lock_flow: bpy.props.BoolProperty(
        name="固定当前流",
        description="勾选后固定当前显示的流，不会随活动节点变化而刷新。取消勾选后恢复自动刷新",
        default=False,
        update=_save_and_redraw_update
    )
    
    enable_type_based_colors: bpy.props.BoolProperty(
        name="根据数据类型着色",
        description="启用后，不同数据类型的连线会使用不同的色相偏移，便于区分数据类型",
        default=False,
        update=_save_and_redraw_update
    )
    
    # 移除彩虹色选项，只保留自定义（但保留属性以兼容旧数据）
    connection_color_type: bpy.props.EnumProperty(
        name="连线颜色类型",
        description="选择连线颜色的类型",
        items=[
            ('CUSTOM', '自定义', '使用自定义渐变色显示连线'),
        ],
        default='CUSTOM',
        update=_save_and_redraw_update
    )
    
    # --- 动态颜色系统：Constant（常量）类型 ---
    gradient_colors: bpy.props.CollectionProperty(type=GradientColorItem)
    gradient_color_count: bpy.props.IntProperty(
        name="颜色数量",
        description="常量类型渐变中使用的颜色数量",
        default=5,
        min=2,
        max=10,
        update=lambda self, context: self._update_color_count_and_save(context)
    )
    
    # --- 动态颜色系统：Field（域）类型 ---
    field_gradient_colors: bpy.props.CollectionProperty(type=GradientColorItem)
    field_gradient_color_count: bpy.props.IntProperty(
        name="域类型颜色数量",
        description="域类型渐变中使用的颜色数量",
        default=5,
        min=2,
        max=10,
        update=lambda self, context: self._update_field_color_count_and_save(context)
    )

    # --- 动态颜色系统：端点空心罩 ---
    endpoint_gradient_colors: bpy.props.CollectionProperty(type=GradientColorItem)
    endpoint_gradient_color_count: bpy.props.IntProperty(
        name="端点颜色数量",
        description="端点空心罩渐变中使用的颜色数量",
        default=5,
        min=2,
        max=10,
        update=lambda self, context: self._update_endpoint_color_count_and_save(context)
    )
    
    def _update_color_count_and_save(self, context):
        """更新常量颜色数量并保存"""
        self._update_color_count()
        _force_redraw_update()
        _autosave_settings(context)
    
    def _update_color_count(self):
        """更新常量颜色数量时，确保集合中有足够的颜色项"""
        # 关键修复：添加 try-except 块以防止在文件加载期间修改 ID 数据
        try:
            target_count = self.gradient_color_count
            current_count = len(self.gradient_colors)
            
            # 如果数量减少，只保留前N个
            while len(self.gradient_colors) > target_count:
                self.gradient_colors.remove(len(self.gradient_colors) - 1)
            
            # 如果数量增加，添加默认颜色
            while len(self.gradient_colors) < target_count:
                item = self.gradient_colors.add()
                # 设置一些默认颜色（蓝色系）
                idx = len(self.gradient_colors) - 1
                defaults = [
                    (0.0, 0.5, 1.0),  # 蓝
                    (0.0, 1.0, 0.8),  # 青
                    (1.0, 1.0, 0.0),  # 黄
                    (1.0, 0.5, 0.0),  # 橙
                    (1.0, 0.0, 0.5),  # 红粉
                ]
                if idx < len(defaults):
                    item.color = defaults[idx]
                else:
                    item.color = (1.0, 1.0, 1.0)
                item.alpha = 1.0  # 默认完全不透明
        except AttributeError:
            # 如果在文件加载期间触发，Blender禁止修改ID类，直接忽略
            # 数据的同步将在 on_load_post 中由 load_global_settings 重新触发（那是安全的）
            pass
    
    def _update_field_color_count_and_save(self, context):
        """更新域颜色数量并保存"""
        self._update_field_color_count()
        _force_redraw_update()
        _autosave_settings(context)

    def _update_field_color_count(self):
        """更新域颜色数量时，确保集合中有足够的颜色项"""
        # 关键修复：添加 try-except 块以防止在文件加载期间修改 ID 数据
        try:
            target_count = self.field_gradient_color_count
            current_count = len(self.field_gradient_colors)

            # 如果数量减少，只保留前N个
            while len(self.field_gradient_colors) > target_count:
                self.field_gradient_colors.remove(len(self.field_gradient_colors) - 1)

            # 如果数量增加，添加默认颜色（紫色系，用于区分Field）
            while len(self.field_gradient_colors) < target_count:
                item = self.field_gradient_colors.add()
                # 设置一些默认颜色（紫色系）
                idx = len(self.field_gradient_colors) - 1
                defaults = [
                    (0.8, 0.2, 1.0),  # 紫
                    (0.6, 0.4, 1.0),  # 蓝紫
                    (1.0, 0.4, 0.8),  # 粉紫
                    (0.9, 0.6, 1.0),  # 浅紫
                    (0.7, 0.3, 0.9),  # 深紫
                ]
                if idx < len(defaults):
                    item.color = defaults[idx]
                else:
                    item.color = (0.8, 0.8, 0.8)
                item.alpha = 1.0  # 默认完全不透明
        except AttributeError:
            # 如果在文件加载期间触发，Blender禁止修改ID类，直接忽略
            pass

    def _update_endpoint_color_count_and_save(self, context):
        """更新端点空心罩颜色数量并保存"""
        self._update_endpoint_color_count()
        _force_redraw_update()
        _autosave_settings(context)

    def _update_endpoint_color_count(self):
        """更新端点空心罩颜色数量时，确保集合中有足够的颜色项"""
        try:
            target_count = self.endpoint_gradient_color_count

            while len(self.endpoint_gradient_colors) > target_count:
                self.endpoint_gradient_colors.remove(len(self.endpoint_gradient_colors) - 1)

            while len(self.endpoint_gradient_colors) < target_count:
                item = self.endpoint_gradient_colors.add()
                idx = len(self.endpoint_gradient_colors) - 1
                defaults = [
                    (0.0, 0.5, 1.0),
                    (0.0, 1.0, 0.8),
                    (1.0, 1.0, 0.0),
                    (1.0, 0.5, 0.0),
                    (1.0, 0.0, 0.5),
                ]
                if idx < len(defaults):
                    item.color = defaults[idx]
                else:
                    item.color = (1.0, 1.0, 1.0)
                item.alpha = 1.0
        except AttributeError:
            pass
    
    # --- 预设系统 ---
    gradient_presets: bpy.props.CollectionProperty(type=GradientPreset)
    active_preset_index: bpy.props.IntProperty(default=-1)
    last_applied_preset_index: bpy.props.IntProperty(default=-1)  # 最后一次应用的预设索引
    
    animation_speed: bpy.props.FloatProperty(
        name="动画速度",
        description="设置颜色流动动画的速度",
        default=2.0,
        min=0.1,
        max=10.0,
        update=_save_and_redraw_update
    )
    
    line_thickness: bpy.props.FloatProperty(
        name="连线粗细",
        description="设置连线的粗细程度",
        default=5.0,
        min=1.0,
        max=20.0,
        update=_save_and_redraw_update
    )

    node_border_thickness: bpy.props.FloatProperty(
        name="节点边框粗细",
        description="设置节点边框的粗细程度",
        default=3.0,
        min=1.0,
        max=20.0,
        update=_save_and_redraw_update
    )

    endpoint_overlay_size: bpy.props.FloatProperty(
        name="端点尺寸",
        description="调整端点空心罩的整体尺寸",
        default=1.0,
        min=0.1,
        max=1.4,
        update=_save_and_redraw_update
    )

    endpoint_overlay_thickness: bpy.props.FloatProperty(
        name="端点粗细",
        description="调整端点空心罩的描边粗细",
        default=0.78,
        min=0.35,
        max=1.4,
        update=_save_and_redraw_update
    )

    enable_colorful_connections: bpy.props.BoolProperty(
        name="启用彩色连线",
        description="启用或禁用彩色连线功能",
        default=True,
        update=_save_and_redraw_update
    )
    
    overall_opacity: bpy.props.FloatProperty(
        name="整体透明度",
        description="调整所有绘制元素的透明度（0.0=完全透明，1.0=完全不透明）",
        default=1.0,
        min=0.0,
        max=1.0,
        update=_save_and_redraw_update
    )
    
    backing_color_rgb: bpy.props.FloatVectorProperty(
        name="底层背景颜色",
        description="设置连线底层背景的颜色（RGB）",
        subtype='COLOR',
        default=(0.0, 0.0, 0.0),
        min=0.0, max=1.0,
        size=3,  # RGB only
        update=_save_and_redraw_update
    )
    
    backing_color_alpha: bpy.props.FloatProperty(
        name="底层背景透明度",
        description="设置底层背景颜色的透明度（0.0=完全透明，1.0=完全不透明）",
        default=0.55,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        update=_save_and_redraw_update
    )

# 操作符：保存预设
class NODE_OT_save_gradient_preset(bpy.types.Operator):
    """保存当前颜色配置为预设"""
    bl_idname = "node.save_gradient_preset"
    bl_label = "保存预设"
    bl_options = {'REGISTER', 'UNDO'}
    
    preset_name: bpy.props.StringProperty(name="预设名称", default="新预设")
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)
    
    def execute(self, context):
        settings = context.scene.colorful_connections_settings
        preset = settings.gradient_presets.add()
        preset.name = self.preset_name
        
        # 复制当前颜色到预设（包括alpha透明度）
        for color_item in settings.gradient_colors:
            new_color = preset.colors.add()
            new_color.color = color_item.color[:]
            new_color.alpha = getattr(color_item, 'alpha', 1.0)
        
        settings.active_preset_index = len(settings.gradient_presets) - 1
        
        # 保存到文件
        save_presets_to_file(settings)
        _autosave_settings(context)

        return {'FINISHED'}

# 操作符：应用预设
class NODE_OT_apply_gradient_preset(bpy.types.Operator):
    """应用选中的预设"""
    bl_idname = "node.apply_gradient_preset"
    bl_label = "应用预设"
    bl_options = {'REGISTER', 'UNDO'}
    
    preset_index: bpy.props.IntProperty(default=-1)
    
    def execute(self, context):
        settings = context.scene.colorful_connections_settings
        idx = self.preset_index if self.preset_index >= 0 else settings.active_preset_index
        
        if idx < 0 or idx >= len(settings.gradient_presets):
            return {'CANCELLED'}
        
        preset = settings.gradient_presets[idx]
        
        # 清空当前颜色
        settings.gradient_colors.clear()
        
        # 复制预设颜色
        for preset_color in preset.colors:
            new_color = settings.gradient_colors.add()
            new_color.color = preset_color.color[:]
            new_color.alpha = getattr(preset_color, 'alpha', 1.0)
        
        # 更新颜色数量
        settings.gradient_color_count = len(preset.colors)
        settings.active_preset_index = idx
        settings.last_applied_preset_index = idx  # 记录最后应用的预设
        
        # 自动保存当前应用结果
        _autosave_settings(context)

        return {'FINISHED'}

# 操作符：手动保存设置
class NODE_OT_save_settings_manual(bpy.types.Operator):
    """手动保存所有设置到文件"""
    bl_idname = "node.save_settings_manual"
    bl_label = "保存设置"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        settings = context.scene.colorful_connections_settings
        _save_global_settings_internal(settings)
        self.report({'INFO'}, "设置已保存")
        return {'FINISHED'}

# 操作符：删除预设
class NODE_OT_delete_gradient_preset(bpy.types.Operator):
    """删除预设"""
    bl_idname = "node.delete_gradient_preset"
    bl_label = "删除预设"
    bl_options = {'REGISTER', 'UNDO'}
    
    preset_index: bpy.props.IntProperty(default=-1)
    
    def execute(self, context):
        settings = context.scene.colorful_connections_settings
        idx = self.preset_index if self.preset_index >= 0 else settings.active_preset_index
        
        if idx < 0 or idx >= len(settings.gradient_presets):
            return {'CANCELLED'}
        
        settings.gradient_presets.remove(idx)
        
        # 调整活动索引
        if settings.active_preset_index >= len(settings.gradient_presets):
            settings.active_preset_index = len(settings.gradient_presets) - 1
        
        # 只保存预设到文件（预设操作应该保存，但全局设置不自动保存）
        try:
            save_presets_to_file(settings)
            _autosave_settings(context)
        except Exception as e:
            print(f"删除预设时出错: {e}")
            import traceback
            traceback.print_exc()
        
        return {'FINISHED'}

class NODE_PT_colorful_connections_panel(bpy.types.Panel):
    """彩色连线面板"""
    bl_label = "彩色连线设置"
    bl_idname = "NODE_PT_colorful_connections_panel"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "彩色连线"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # 获取面板设置
        settings = scene.colorful_connections_settings

        col = layout.column()

        # 启用/禁用开关
        col.prop(settings, "enable_colorful_connections")

        box_general = col.box()
        box_general.label(text="基础设置:", icon='PREFERENCES')
        box_general.prop(settings, "connection_color_type", text="颜色类型")
        box_general.prop(settings, "overall_opacity")

        col.separator()

        # --- 预设管理区域（移到顶层） ---
        box_preset = col.box()
        box_preset.label(text="预设方案:", icon='PRESET')
        preset_col = box_preset.column(align=True)

        if len(settings.gradient_presets) > 0:
            preset_col.template_list(
                "UI_UL_gradient_preset_list",
                "",
                settings,
                "gradient_presets",
                settings,
                "active_preset_index",
                rows=2
            )

            button_col = preset_col.column(align=True)
            button_col.operator("node.apply_gradient_preset", text="应用", icon='PLAY')
            button_col.operator("node.save_gradient_preset", text="保存", icon='FILE_TICK')
            button_col.operator("node.delete_gradient_preset", text="删除", icon='TRASH')

            # 如果有预设，默认应用第一个（如果是首次加载）
            if settings.active_preset_index >= 0 and settings.active_preset_index < len(settings.gradient_presets):
                # 自动应用当前选中的预设（如果需要）
                pass
        else:
            preset_col.operator("node.save_gradient_preset", text="保存当前为预设", icon='FILE_TICK')
        
        col.separator()
        
        # --- 追踪逻辑 UI ---
        col.label(text="追踪逻辑:")
        row = col.row()
        row.prop(settings, "trace_mode", expand=True)
        
        if settings.trace_mode == 'ACTIVE_FLOW':
            row = col.row()
            row.prop(settings, "flow_direction", expand=True)
            
            # 固定流选项
            row = col.row()
            row.prop(settings, "lock_flow", text="固定当前流", icon='LOCKED' if settings.lock_flow else 'UNLOCKED')
            
            # 快速选择按钮
            op = col.operator("node.select_flow_nodes", text="选中数据流节点", icon='RESTRICT_SELECT_OFF')
        
        col.separator()
        
        # --- 数据类型着色选项 ---
        col.label(text="数据类型着色:")
        box_type = col.box()
        box_type.prop(settings, "enable_type_based_colors", text="根据数据类型着色", icon='COLOR')
        if settings.enable_type_based_colors:
            box_type.label(text="不同数据类型将使用不同的色相偏移", icon='INFO')
        
        col.separator()
        
        # --- 颜色设置：分为Constant和Field两个区域 ---
        col.label(text="颜色设置:")
        
        # Constant（常量）类型配色
        box_constant = col.box()
        box_constant.label(text="常量类型 (Constant):", icon='NODE')
        
        # 颜色数量控制
        row = box_constant.row()
        row.label(text="颜色数量:")
        row.prop(settings, "gradient_color_count", text="")
        
        box_constant.separator()
        
        # 紧凑的颜色列表
        box_constant.label(text="颜色列表 (循环渐变):")
        active_count = settings.gradient_color_count
        colors = settings.gradient_colors

        # 注意：不在 draw 方法中修改场景数据，如果颜色不足，只显示已有的颜色
        # 初始化会在注册时或场景加载后完成

        # 显示颜色列表，每个颜色包含颜色选择器和透明度滑块
        # 只显示已存在的颜色项，最多显示 active_count 个
        display_count = min(active_count, len(colors))
        for idx in range(display_count):
            # 确保alpha属性存在（兼容旧数据）
            if not hasattr(colors[idx], 'alpha'):
                colors[idx].alpha = 1.0

            item_col = box_constant.column(align=True)
            item_col.prop(colors[idx], "color", text=f"颜色 {idx+1}")
            item_col.prop(colors[idx], "alpha", text="透明度", slider=True)
        
        # 如果颜色不足，显示提示（但不在这里修改场景数据）
        if len(colors) < active_count:
            box_constant.label(text=f"颜色数量不足，请重新加载插件", icon='ERROR')
        
        col.separator()
        
        # Field（域）类型配色
        box_field = col.box()
        box_field.label(text="域类型 (Field):", icon='PHYSICS')

        # 颜色数量控制
        row = box_field.row()
        row.label(text="颜色数量:")
        row.prop(settings, "field_gradient_color_count", text="")

        box_field.separator()

        # 紧凑的颜色列表
        box_field.label(text="颜色列表 (循环渐变):")
        field_active_count = settings.field_gradient_color_count
        field_colors = settings.field_gradient_colors

        # 注意：不在 draw 方法中修改场景数据，如果颜色不足，只显示已有的颜色
        # 初始化会在注册时或场景加载后完成

        # 显示颜色列表，每个颜色包含颜色选择器和透明度滑块
        # 只显示已存在的颜色项，最多显示 field_active_count 个
        field_display_count = min(field_active_count, len(field_colors))
        for idx in range(field_display_count):
            # 确保alpha属性存在（兼容旧数据）
            if not hasattr(field_colors[idx], 'alpha'):
                field_colors[idx].alpha = 1.0

            item_col = box_field.column(align=True)
            item_col.prop(field_colors[idx], "color", text=f"颜色 {idx+1}")
            item_col.prop(field_colors[idx], "alpha", text="透明度", slider=True)

        # 如果颜色不足，显示提示（但不在这里修改场景数据）
        if len(field_colors) < field_active_count:
            box_field.label(text=f"颜色数量不足，请重新加载插件", icon='ERROR')

        col.separator()

        # Endpoint（端点空心罩）配色
        box_endpoint = col.box()
        box_endpoint.label(text="端点空心罩:", icon='MESH_CIRCLE')

        row = box_endpoint.row()
        row.label(text="颜色数量:")
        row.prop(settings, "endpoint_gradient_color_count", text="")
        box_endpoint.prop(settings, "endpoint_overlay_size")
        box_endpoint.prop(settings, "endpoint_overlay_thickness")

        box_endpoint.separator()
        box_endpoint.label(text="颜色列表 (循环渐变):")
        endpoint_active_count = settings.endpoint_gradient_color_count
        endpoint_colors = settings.endpoint_gradient_colors

        endpoint_display_count = min(endpoint_active_count, len(endpoint_colors))
        for idx in range(endpoint_display_count):
            if not hasattr(endpoint_colors[idx], 'alpha'):
                endpoint_colors[idx].alpha = 1.0

            item_col = box_endpoint.column(align=True)
            item_col.prop(endpoint_colors[idx], "color", text=f"颜色 {idx+1}")
            item_col.prop(endpoint_colors[idx], "alpha", text="透明度", slider=True)

        if len(endpoint_colors) < endpoint_active_count:
            box_endpoint.label(text=f"颜色数量不足，请重新加载插件", icon='ERROR')
        
        col.separator()
        col.label(text="外观设置:")
        col.prop(settings, "line_thickness")
        col.prop(settings, "node_border_thickness")
        col.prop(settings, "animation_speed")

        col.separator()
        col.label(text="底层背景:")
        backing_col = col.column(align=True)
        backing_col.prop(settings, "backing_color_rgb", text="颜色")
        backing_col.prop(settings, "backing_color_alpha", text="透明度", slider=True)
        
        col.separator()
        
        # 手动保存按钮
        col.operator("node.save_settings_manual", text="保存设置", icon='FILE_TICK')
        
        col.separator()
        col.label(text="编辑器设置:")
        layout.prop(context.preferences.themes[0].node_editor, "noodle_curving", text="曲线因子")

classes = [
    UI_UL_gradient_preset_list,
    GradientColorItem,
    GradientPreset,
    ColorfulConnectionsSettings,
    NODE_PT_colorful_connections_panel,
    NODE_OT_save_gradient_preset,
    NODE_OT_apply_gradient_preset,
    NODE_OT_delete_gradient_preset,
    NODE_OT_save_settings_manual,
]

# 场景加载后的回调函数
@bpy.app.handlers.persistent
def on_load_post(dummy):
    """场景加载后，从插件目录重新加载设置"""
    # 使用延迟执行，确保场景完全加载
    def init_after_load():
        try:
            _initialize_scene_settings()
        except Exception as e:
            print(f"加载后初始化失败: {e}")
            import traceback
            traceback.print_exc()
        return None  # timer 只执行一次

    # 延迟0.5秒执行，确保场景完全加载
    bpy.app.timers.register(init_after_load, first_interval=0.5)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.colorful_connections_settings = bpy.props.PointerProperty(type=ColorfulConnectionsSettings)

    # 注册场景加载后的回调
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)

    # 初始化默认颜色和加载设置（插件启用时）
    def init_default_colors():
        try:
            _initialize_scene_settings(_safe_get_scene())
        except Exception as e:
            print(f"初始化设置失败: {e}")
            import traceback
            traceback.print_exc()

    # 延迟初始化
    bpy.app.timers.register(init_default_colors, first_interval=0.1)

def unregister():
    # 移除场景加载后的回调
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.colorful_connections_settings