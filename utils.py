import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from math import isfinite
import time
from mathutils import Vector
import colorsys
from ctypes import c_void_p, c_float
from math import pi, sqrt, exp, hypot, sin, cos
import re

# Socket类型到色相偏移的映射（基于HSV色相，范围0-360度）
SOCKET_TYPE_HUE_OFFSETS = {
    'NodeSocketFloat': 0.0,
    'NodeSocketInt': 18.0,
    'NodeSocketVector': 35.0,
    'NodeSocketColor': -25.0,
    'NodeSocketShader': 140.0,
    'NodeSocketBool': -55.0,
    'NodeSocketString': 70.0,
    'NodeSocketObject': 105.0,
    'NodeSocketImage': -40.0,
    'NodeSocketGeometry': 170.0,
    'NodeSocketCollection': 120.0,
    'NodeSocketTexture': -70.0,
    'NodeSocketMaterial': 150.0,
    'NodeSocketRotation': 55.0,
    'NodeSocketMenu': 85.0,
    'NodeSocketMatrix': 95.0,
}

NODE_LAYOUT_DEFAULTS = {
    'hidden_header_offset': 9.0,
    'reroute_half_size': 5.5,
    'socket_header_height': 32.0,
    'socket_row_height': 21.0,
    'socket_output_nudge': 0.5,
}


def get_layout_metrics():
    prefs = bpy.context.preferences.system
    scale = max(0.01, float(prefs.ui_scale))
    pixel_size = max(1.0, float(prefs.pixel_size))
    return {
        'scale': scale,
        'pixel_size': pixel_size,
        'hidden_header_offset': NODE_LAYOUT_DEFAULTS['hidden_header_offset'] * scale,
        'reroute_half_size': NODE_LAYOUT_DEFAULTS['reroute_half_size'] * scale,
        'socket_header_height': NODE_LAYOUT_DEFAULTS['socket_header_height'] * scale,
        'socket_row_height': NODE_LAYOUT_DEFAULTS['socket_row_height'] * scale,
        'socket_output_nudge': NODE_LAYOUT_DEFAULTS['socket_output_nudge'] * scale,
    }


def get_socket_type_name(socket):
    """获取socket的类型名称"""
    if hasattr(socket, 'bl_idname'):
        return socket.bl_idname
    elif hasattr(socket, 'type'):
        # 兼容性：如果只有type属性，尝试转换
        type_map = {
            'VALUE': 'NodeSocketFloat',
            'INT': 'NodeSocketInt',
            'VECTOR': 'NodeSocketVector',
            'RGBA': 'NodeSocketColor',
            'SHADER': 'NodeSocketShader',
            'BOOLEAN': 'NodeSocketBool',
            'STRING': 'NodeSocketString',
            'OBJECT': 'NodeSocketObject',
            'IMAGE': 'NodeSocketImage',
            'GEOMETRY': 'NodeSocketGeometry',
            'COLLECTION': 'NodeSocketCollection',
            'TEXTURE': 'NodeSocketTexture',
            'MATERIAL': 'NodeSocketMaterial',
            'ROTATION': 'NodeSocketRotation',
            'MENU': 'NodeSocketMenu',
            'MATRIX': 'NodeSocketMatrix',
        }
        return type_map.get(socket.type, 'NodeSocketFloat')
    return 'NodeSocketFloat'  # 默认

def shift_hue(rgb, hue_offset):
    """
    对RGB颜色进行HSV色相偏移
    rgb: (r, g, b) 或 (r, g, b, a)，值范围0-1
    hue_offset: 色相偏移角度（度），范围-180到180
    返回: (r, g, b, a) 格式的颜色
    """
    if len(rgb) >= 3:
        r, g, b = rgb[0], rgb[1], rgb[2]
        alpha = rgb[3] if len(rgb) >= 4 else 1.0
    else:
        return rgb
    
    # 转换为HSV
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    
    # 偏移色相（转换为0-1范围）
    h_offset_normalized = hue_offset / 360.0
    h_new = (h + h_offset_normalized) % 1.0
    
    # 转回RGB
    r_new, g_new, b_new = colorsys.hsv_to_rgb(h_new, s, v)
    
    return (r_new, g_new, b_new, alpha)

def get_socket_hue_offset(socket):
    """获取socket类型的色相偏移值"""
    socket_type = get_socket_type_name(socket)
    return SOCKET_TYPE_HUE_OFFSETS.get(socket_type, 0.0)

def get_socket_circle_size(socket, zoom, base_size=5.0):
    """
    根据socket类型返回圆圈大小
    不同数据类型使用不同的显示尺寸，避免全是小圆点
    """
    socket_type = get_socket_type_name(socket)
    # 根据socket类型分配不同的大小系数
    size_multipliers = {
        'NodeSocketFloat': 1.0,      # 标准大小
        'NodeSocketInt': 1.1,        # 略大
        'NodeSocketVector': 1.15,    # 更大
        'NodeSocketColor': 1.2,      # 更大
        'NodeSocketShader': 1.25,    # 最大
        'NodeSocketBool': 0.9,       # 略小
        'NodeSocketString': 1.1,
        'NodeSocketObject': 1.15,
        'NodeSocketImage': 1.2,
        'NodeSocketGeometry': 1.25,
        'NodeSocketCollection': 1.1,
        'NodeSocketTexture': 1.2,
        'NodeSocketMaterial': 1.2,
        'NodeSocketRotation': 1.15,
        'NodeSocketMatrix': 1.25,
    }
    multiplier = size_multipliers.get(socket_type, 1.0)
    return base_size * multiplier * zoom

def apply_type_based_color_shift(colors, from_socket, to_socket, offset_strength=0.4):
    """
    根据socket类型对颜色进行色相偏移
    offset_strength: 偏移强度（0-1），0.4表示偏移40%的强度，避免颜色变化过大
    """
    # 使用目标socket的类型（因为数据流向目标）
    target_socket = to_socket
    hue_offset = get_socket_hue_offset(target_socket)
    
    # 应用强度系数
    effective_offset = hue_offset * offset_strength
    
    # 对所有颜色应用偏移
    shifted_colors = []
    for color in colors:
        shifted = shift_hue(color, effective_offset)
        shifted_colors.append(shifted)
    
    return shifted_colors

def is_field_link(tree, link):
    """
    判断是否为Field(场)数据流连线
    只在几何节点编辑器中有效
    """
    try:
        if not tree or getattr(tree, 'type', '') != 'GEOMETRY':
            return False
        fs = getattr(link, 'from_socket', None)
        if fs is None:
            return False
        
        # 方法1: 检查socket的is_field属性（Blender 3.0+）
        if hasattr(fs, 'is_field'):
            try:
                field_value = fs.is_field
                if field_value:
                    return True
            except:
                pass
        
        # 方法2: 检查socket的display_shape（Field通常使用DIAMOND形状）
        if hasattr(fs, 'display_shape'):
            try:
                # SOCK_DISPLAY_SHAPE_DIAMOND = 'DIAMOND' 通常表示Field
                if fs.display_shape == 'DIAMOND':
                    return True
            except:
                pass
        
        # 方法3: 通过socket的内部属性判断（使用指针访问）
        try:
            # 尝试通过socket的内部结构判断
            # Blender的socket可能有field相关的内部标志
            socket_ptr = fs.as_pointer()
            if socket_ptr:
                # 在某些Blender版本中，可以通过检查socket的类型标志
                # 这里我们尝试通过其他方式判断
                pass
        except:
            pass
        
        # 方法4: 检查连接的节点类型（某些节点类型通常输出Field）
        from_node = getattr(link, 'from_node', None)
        if from_node:
            # 某些节点类型通常输出Field数据
            field_output_nodes = [
                'ATTRIBUTE_DOMAIN', 'FIELD_AT_INDEX', 'SAMPLE_INDEX', 
                'SAMPLE_NEAREST', 'SAMPLE_NEAREST_SURFACE', 'INTERPOLATE_DOMAIN',
                'EVALUATE_AT_INDEX', 'EVALUATE_ON_DOMAIN'
            ]
            if from_node.type in field_output_nodes:
                return True
            
            # 检查节点名称（某些节点名称包含field相关关键词）
            node_name_lower = (getattr(from_node, 'name', '') or '').lower()
            if 'field' in node_name_lower or 'attribute' in node_name_lower:
                return True
        
        # 方法5: 检查目标socket是否接受Field（如果目标socket是Field类型，源也可能是）
        ts = getattr(link, 'to_socket', None)
        if ts:
            if hasattr(ts, 'is_field'):
                try:
                    if ts.is_field:
                        return True
                except:
                    pass
            if hasattr(ts, 'display_shape'):
                try:
                    if ts.display_shape == 'DIAMOND':
                        return True
                except:
                    pass
                    
    except Exception as e:
        # 调试用：可以打印错误信息
        # print(f"Error checking field link: {e}")
        pass
    return False

def create_dashed_line_segments_smooth(points, dash_length=10.0, gap_length=5.0, time_offset=0.0):
    """
    平滑的虚线生成算法，确保虚线均匀且连续（优化版本）
    """
    if len(points) < 2:
        return []
    
    # 预计算累积距离（避免重复计算）
    cumulative_distances = [0.0]
    path_length = 0.0
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        seg_len = hypot(dx, dy)
        path_length += seg_len
        cumulative_distances.append(path_length)
    
    if path_length == 0:
        return []
    
    pattern_length = dash_length + gap_length
    offset = time_offset % pattern_length
    
    dashed_segments = []
    current_pos = -offset
    max_iterations = int(path_length / min(dash_length, gap_length)) + 10  # 防止无限循环
    iteration = 0
    
    # 沿着路径生成均匀的虚线段（优化版本，限制生成数量）
    max_segments_limit = 20  # 限制最大虚线段数量，防止性能问题
    
    while current_pos < path_length and iteration < max_iterations and len(dashed_segments) < max_segments_limit:
        iteration += 1
        pattern_pos = (current_pos + offset + pattern_length) % pattern_length
        
        if pattern_pos < dash_length:
            # 在虚线部分
            dash_start = current_pos
            dash_end = min(current_pos + (dash_length - pattern_pos), path_length)
            
            if dash_end > dash_start and (dash_end - dash_start) >= 2.0:  # 最小长度限制提高到2像素
                # 生成虚线段（大幅减少采样点数量，提高性能）
                segment = []
                dash_seg_length = dash_end - dash_start
                # 最小化采样点：每8像素一个采样点，最少2个点，最多4个点
                num_samples = max(2, min(4, int(dash_seg_length / 8.0)))
                
                for j in range(num_samples + 1):
                    t = j / num_samples if num_samples > 0 else 0
                    dist = dash_start + (dash_end - dash_start) * t
                    point = get_point_at_distance(points, cumulative_distances, dist)
                    if point:
                        segment.append(point)
                
                if len(segment) >= 2:
                    dashed_segments.append(segment)
            
            # 移动到下一个位置（确保有最小步进，防止死循环）
            current_pos = max(dash_end, current_pos + 1.0)
            if current_pos >= path_length:
                break
        else:
            # 跳过间隙（确保有最小步进）
            gap_end = min(current_pos + (pattern_length - pattern_pos), path_length)
            current_pos = max(gap_end, current_pos + 1.0)
            if current_pos >= path_length:
                break
    
    return dashed_segments

def create_dashed_line_segments(points, dash_length=10.0, gap_length=5.0, time_offset=0.0):
    """
    将连续的点列表转换为虚线段的列表
    points: 连续的点列表 [(x1, y1), (x2, y2), ...]
    dash_length: 每段虚线的长度（像素）
    gap_length: 间隙长度（像素）
    time_offset: 时间偏移，用于动画效果（像素单位）
    返回: 虚线段的列表，每个元素是一个点列表
    """
    if len(points) < 2:
        return []
    
    # 计算路径上每个点的累积距离
    cumulative_distances = [0.0]
    total_length = 0.0
    
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        seg_len = hypot(dx, dy)
        total_length += seg_len
        cumulative_distances.append(total_length)
    
    if total_length == 0:
        return []
    
    # 虚线模式：dash + gap 循环
    pattern_length = dash_length + gap_length
    
    # 应用时间偏移（循环，确保偏移在有效范围内）
    offset = time_offset % pattern_length
    
    # 沿着路径生成均匀的虚线段
    dashed_segments = []
    current_pos = -offset  # 从负偏移开始，这样动画会向前移动
    
    # 沿着路径生成虚线段
    while current_pos < total_length:
        # 计算当前模式位置（0 到 pattern_length）
        pattern_pos = (current_pos + offset + pattern_length) % pattern_length
        
        # 判断是否在虚线部分
        if pattern_pos < dash_length:
            # 计算虚线段的起始和结束位置
            dash_start = current_pos
            dash_end = min(current_pos + (dash_length - pattern_pos), total_length)
            
            # 如果虚线段长度足够，生成它
            if dash_end > dash_start:
                segment_points = []
                # 沿着虚线段的路径采样点
                num_samples = max(2, int((dash_end - dash_start) / 2.0))  # 每2像素一个采样点
                for i in range(num_samples + 1):
                    t = i / num_samples if num_samples > 0 else 0
                    dist = dash_start + (dash_end - dash_start) * t
                    point = get_point_at_distance(points, cumulative_distances, dist)
                    if point:
                        segment_points.append(point)
                
                if len(segment_points) >= 2:
                    dashed_segments.append(segment_points)
            
            # 移动到虚线段的结束位置
            current_pos = dash_end
        else:
            # 跳过间隙部分
            gap_start = current_pos
            gap_end = min(current_pos + (pattern_length - pattern_pos), total_length)
            current_pos = gap_end
    
    return dashed_segments

def get_point_at_path_distance(points, target_distance):
    """
    在路径上找到指定距离处的点（直接计算，不需要预计算累积距离）
    points: 点列表
    target_distance: 目标距离
    返回: (x, y) 坐标元组，如果超出范围返回None
    """
    if len(points) < 2:
        return None
    
    if target_distance < 0:
        return points[0]
    
    # 沿着路径累加距离，找到目标距离所在的线段
    current_dist = 0.0
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        seg_len = hypot(dx, dy)
        
        if current_dist + seg_len >= target_distance:
            # 在这个线段内
            if seg_len < 1e-6:
                return p1
            
            t = (target_distance - current_dist) / seg_len
            x = p1[0] + (p2[0] - p1[0]) * t
            y = p1[1] + (p2[1] - p1[1]) * t
            return (x, y)
        
        current_dist += seg_len
    
    # 超出范围，返回最后一个点
    return points[-1]

def get_point_at_distance(points, cumulative_distances, target_distance):
    """
    在路径上找到指定距离处的点
    points: 点列表
    cumulative_distances: 累积距离列表
    target_distance: 目标距离
    返回: (x, y) 坐标元组，如果超出范围返回None
    """
    if target_distance < 0:
        target_distance = 0
    if target_distance >= cumulative_distances[-1]:
        return points[-1] if points else None
    
    # 找到目标距离所在的线段
    for i in range(len(cumulative_distances) - 1):
        dist_start = cumulative_distances[i]
        dist_end = cumulative_distances[i + 1]
        
        if dist_start <= target_distance <= dist_end:
            # 在这个线段内插值
            if abs(dist_end - dist_start) < 1e-6:
                return points[i]
            
            t = (target_distance - dist_start) / (dist_end - dist_start)
            p1 = points[i]
            p2 = points[i + 1]
            x = p1[0] + (p2[0] - p1[0]) * t
            y = p1[1] + (p2[1] - p1[1]) * t
            return (x, y)
    
    # 如果没找到，返回最后一个点
    return points[-1] if points else None

def filter_border_path_near_sockets(path, socket_masks):
    if not path or len(path) < 2:
        return []
    return split_polyline_by_socket_masks(path, socket_masks)


def point_in_socket_mask(point, socket_mask):
    if not point or not socket_mask:
        return False

    cx, cy, radius, shape_id = socket_mask
    if radius <= 0.0:
        return False

    dx = (point[0] - cx) / radius
    dy = (point[1] - cy) / radius

    if shape_id < 0.5:
        return dx * dx + dy * dy <= 1.0
    if shape_id < 1.5:
        return abs(dx) <= 1.0 and abs(dy) <= 1.0
    return abs(dx) + abs(dy) <= 1.0


def _lerp_point(p0, p1, t):
    return (
        p0[0] + (p1[0] - p0[0]) * t,
        p0[1] + (p1[1] - p0[1]) * t,
    )


def _points_almost_equal(p0, p1, epsilon=0.01):
    return abs(p0[0] - p1[0]) <= epsilon and abs(p0[1] - p1[1]) <= epsilon


def _offset_point_along_segment(p0, p1, point, distance):
    if distance <= 1e-6:
        return point

    segment = Vector((p1[0] - p0[0], p1[1] - p0[1]))
    seg_len = segment.length
    if seg_len <= 1e-6:
        return point

    direction = segment / seg_len
    point_vec = Vector(point)
    start_vec = Vector(p0)
    end_vec = Vector(p1)
    start_dist = (point_vec - start_vec).length
    end_dist = (end_vec - point_vec).length

    if start_dist <= end_dist:
        adjusted = point_vec - direction * min(distance, start_dist)
    else:
        adjusted = point_vec + direction * min(distance, end_dist)

    return (adjusted.x, adjusted.y)


def _append_unique_t(ts, t, epsilon=1e-6):
    if t < -epsilon or t > 1.0 + epsilon:
        return

    t = max(0.0, min(1.0, t))
    for existing in ts:
        if abs(existing - t) <= epsilon:
            return
    ts.append(t)


def _get_segment_mask_intersections(p0, p1, socket_mask):
    cx, cy, radius, shape_id = socket_mask
    if radius <= 0.0:
        return []

    ax = (p0[0] - cx) / radius
    ay = (p0[1] - cy) / radius
    bx = (p1[0] - cx) / radius
    by = (p1[1] - cy) / radius
    dx = bx - ax
    dy = by - ay

    intersections = []
    tolerance = 1e-5

    if shape_id < 0.5:
        a = dx * dx + dy * dy
        b = 2.0 * (ax * dx + ay * dy)
        c = ax * ax + ay * ay - 1.0
        if a <= tolerance:
            return []

        discriminant = b * b - 4.0 * a * c
        if discriminant < -tolerance:
            return []
        discriminant = max(discriminant, 0.0)
        root = sqrt(discriminant)
        _append_unique_t(intersections, (-b - root) / (2.0 * a))
        _append_unique_t(intersections, (-b + root) / (2.0 * a))
        return sorted(intersections)

    if shape_id < 1.5:
        if abs(dx) > tolerance:
            for boundary_x in (-1.0, 1.0):
                t = (boundary_x - ax) / dx
                if 0.0 - tolerance <= t <= 1.0 + tolerance:
                    y = ay + dy * t
                    if abs(y) <= 1.0 + tolerance:
                        _append_unique_t(intersections, t)
        if abs(dy) > tolerance:
            for boundary_y in (-1.0, 1.0):
                t = (boundary_y - ay) / dy
                if 0.0 - tolerance <= t <= 1.0 + tolerance:
                    x = ax + dx * t
                    if abs(x) <= 1.0 + tolerance:
                        _append_unique_t(intersections, t)
        return sorted(intersections)

    plane_constants = (1.0, 1.0, 1.0, 1.0)
    plane_factors = (
        (1.0, 1.0),
        (1.0, -1.0),
        (-1.0, 1.0),
        (-1.0, -1.0),
    )
    for (fx, fy), plane_constant in zip(plane_factors, plane_constants):
        denominator = fx * dx + fy * dy
        if abs(denominator) <= tolerance:
            continue
        numerator = plane_constant - (fx * ax + fy * ay)
        t = numerator / denominator
        if 0.0 - tolerance <= t <= 1.0 + tolerance:
            x = ax + dx * t
            y = ay + dy * t
            if abs(x) + abs(y) <= 1.0 + tolerance:
                _append_unique_t(intersections, t)
    return sorted(intersections)


def _get_segment_mask_interval(p0, p1, socket_mask):
    intersections = [0.0, 1.0]
    for t in _get_segment_mask_intersections(p0, p1, socket_mask):
        _append_unique_t(intersections, t)
    intersections.sort()

    inside_ranges = []
    for i in range(len(intersections) - 1):
        t0 = intersections[i]
        t1 = intersections[i + 1]
        if t1 - t0 <= 1e-6:
            continue
        mid = _lerp_point(p0, p1, (t0 + t1) * 0.5)
        if point_in_socket_mask(mid, socket_mask):
            inside_ranges.append((t0, t1))

    if not inside_ranges:
        return None

    return inside_ranges[0][0], inside_ranges[-1][1]


def _clip_segment_outside_socket_mask(p0, p1, socket_mask):
    interval = _get_segment_mask_interval(p0, p1, socket_mask)
    if interval is None:
        return [(p0, p1)]

    start_t, end_t = interval
    if end_t - start_t <= 1e-5:
        return [(p0, p1)]

    segment = Vector((p1[0] - p0[0], p1[1] - p0[1]))
    seg_len = segment.length
    if seg_len <= 1e-6:
        return []

    _, _, radius, _ = socket_mask
    cap_overlap = max(0.35, min(radius * 0.18, 1.35))
    overlap_t = min((end_t - start_t) * 0.5, cap_overlap / seg_len)

    clipped_segments = []
    if start_t > 1e-5:
        end_point = _lerp_point(p0, p1, min(start_t + overlap_t, end_t))
        if not _points_almost_equal(p0, end_point):
            clipped_segments.append((p0, end_point))
    if end_t < 1.0 - 1e-5:
        start_point = _lerp_point(p0, p1, max(end_t - overlap_t, start_t))
        if not _points_almost_equal(start_point, p1):
            clipped_segments.append((start_point, p1))
    return clipped_segments


def _split_polyline_by_single_socket_mask(points, socket_mask):
    result = []
    current_segment = []

    for i in range(len(points) - 1):
        p0 = points[i]
        p1 = points[i + 1]
        clipped_parts = _clip_segment_outside_socket_mask(p0, p1, socket_mask)

        if not clipped_parts:
            if len(current_segment) >= 2:
                result.append(current_segment)
            current_segment = []
            continue

        for part_index, (start_point, end_point) in enumerate(clipped_parts):
            if _points_almost_equal(start_point, end_point):
                continue

            if not current_segment:
                current_segment = [start_point, end_point]
            elif _points_almost_equal(current_segment[-1], start_point):
                if not _points_almost_equal(current_segment[-1], end_point):
                    current_segment.append(end_point)
            else:
                if len(current_segment) >= 2:
                    result.append(current_segment)
                current_segment = [start_point, end_point]

            if part_index != len(clipped_parts) - 1:
                if len(current_segment) >= 2:
                    result.append(current_segment)
                current_segment = []

    if len(current_segment) >= 2:
        result.append(current_segment)

    return result


def split_polyline_by_socket_masks(points, socket_masks):
    if not points or len(points) < 2:
        return []
    if not socket_masks:
        return [points]

    segments = [points]
    for socket_mask in socket_masks:
        next_segments = []
        for segment in segments:
            next_segments.extend(_split_polyline_by_single_socket_mask(segment, socket_mask))
        segments = next_segments
        if not segments:
            break

    return [segment for segment in segments if len(segment) >= 2]


def _get_socket_pointer(socket):
    if not socket:
        return None
    try:
        return socket.as_pointer()
    except Exception:
        return id(socket)


SOCKET_MASK_SHAPES = {
    'CIRCLE': 0.0,
    'SQUARE': 1.0,
    'DIAMOND': 2.0,
}


def get_socket_shape_name(socket):
    shape = getattr(socket, 'display_shape', 'CIRCLE') or 'CIRCLE'
    if shape.endswith('_DOT'):
        shape = shape[:-4]
    if shape not in SOCKET_MASK_SHAPES:
        shape = 'SQUARE' if get_socket_type_name(socket) == 'NodeSocketGeometry' else 'CIRCLE'
    return shape


def get_socket_mask_radius(socket, zoom, clip_width=0.0, extra_padding=0.0):
    shape = get_socket_shape_name(socket)
    base_radius = 4.2 * zoom
    if shape == 'SQUARE':
        base_radius = 4.45 * zoom
    elif shape == 'DIAMOND':
        base_radius = 4.7 * zoom
    elif shape == 'GEOMETRY_TALL':
        base_radius = 4.45 * zoom

    line_padding = max(0.0, clip_width) * 0.08
    return max(base_radius + line_padding + extra_padding, 3.8 * zoom + 0.35)


def get_socket_overlay_shape_name(socket):
    if get_socket_type_name(socket) == 'NodeSocketGeometry':
        return 'GEOMETRY_TALL'
    return get_socket_shape_name(socket)


def get_socket_overlay_dims(socket, zoom, clip_width=0.0, extra_padding=0.0, overlay_size=1.0):
    shape_name = get_socket_overlay_shape_name(socket)
    base_radius = get_socket_mask_radius(socket, zoom, clip_width=clip_width, extra_padding=extra_padding)
    overlay_scale = max(0.1, float(overlay_size))
    shape_scale = 0.84 if shape_name == 'SQUARE' else 1.0
    if shape_name != 'GEOMETRY_TALL':
        radius = base_radius * overlay_scale * shape_scale
        return shape_name, radius, radius

    metrics = get_layout_metrics()
    half_width = max(base_radius, 4.0 * zoom + max(0.0, clip_width) * 0.05) * overlay_scale * 0.76
    row_half_height = metrics['socket_row_height'] * 0.5
    desired_half_height = max(
        half_width * 1.35,
        row_half_height * 0.72,
        7.2 * zoom + max(0.0, clip_width) * 0.08 + extra_padding * 0.45,
    ) * overlay_scale * 0.9
    max_half_height = max(row_half_height - metrics['pixel_size'], half_width * 1.15)
    half_height = min(desired_half_height, max_half_height)
    half_height = max(half_height, half_width * 1.15)
    return shape_name, half_width, half_height





def _append_socket_mask(masks, seen_sockets, socket, center, zoom, clip_width=0.0, extra_padding=0.0):
    if not socket or not center:
        return

    socket_ptr = _get_socket_pointer(socket)
    if socket_ptr in seen_sockets:
        return

    shape_name = get_socket_shape_name(socket)
    radius = get_socket_mask_radius(socket, zoom, clip_width=clip_width, extra_padding=extra_padding)
    masks.append((float(center[0]), float(center[1]), float(radius), SOCKET_MASK_SHAPES[shape_name]))
    seen_sockets.add(socket_ptr)


def collect_node_socket_masks(node, v2d, zoom, border_width=0.0):
    masks = []
    seen_sockets = set()

    for is_output, sockets in ((False, getattr(node, 'inputs', [])), (True, getattr(node, 'outputs', []))):
        for idx, socket in enumerate(sockets):
            if not getattr(socket, 'enabled', True):
                continue
            try:
                sx, sy = get_socket_loc(node, is_output, idx)
                center = v2d.view_to_region(sx, sy, clip=False)
            except Exception:
                continue

            _append_socket_mask(masks, seen_sockets, socket, center, zoom, clip_width=border_width)

    return masks


def _get_socket_overlay_path(center, shape_name, half_width, half_height=None, resolution=20):
    if not center or half_width <= 0.0:
        return []

    if half_height is None:
        half_height = half_width
    if half_height <= 0.0:
        return []

    cx, cy = float(center[0]), float(center[1])
    if shape_name == 'SQUARE':
        path = [
            (cx - half_width, cy - half_height),
            (cx + half_width, cy - half_height),
            (cx + half_width, cy + half_height),
            (cx - half_width, cy + half_height),
            (cx - half_width, cy - half_height),
        ]
        return path

    if shape_name == 'GEOMETRY_TALL':
        path = [
            (cx - half_width, cy - half_height),
            (cx + half_width, cy - half_height),
            (cx + half_width, cy + half_height),
            (cx - half_width, cy + half_height),
            (cx - half_width, cy - half_height),
        ]
        return path

    if shape_name == 'DIAMOND':
        path = [
            (cx, cy - half_height),
            (cx + half_width, cy),
            (cx, cy + half_height),
            (cx - half_width, cy),
            (cx, cy - half_height),
        ]
        return path

    path = []
    steps = max(8, int(resolution))
    for i in range(steps + 1):
        angle = (i / steps) * (2.0 * pi)
        path.append((cx + cos(angle) * half_width, cy + sin(angle) * half_height))
    return path




def append_socket_overlay(target_list, seen_sockets, socket, center, zoom, width, colors=None, overlay_size=1.0):
    if not socket or not center:
        return

    socket_ptr = _get_socket_pointer(socket)
    if socket_ptr in seen_sockets:
        return

    shape_name, half_width, half_height = get_socket_overlay_dims(
        socket,
        zoom,
        clip_width=width,
        extra_padding=max(0.35, width * 0.12),
        overlay_size=overlay_size,
    )
    path = _get_socket_overlay_path(center, shape_name, half_width, half_height)
    if len(path) < 2:
        return

    target_list.append({
        'path': path,
        'socket': socket,
        'colors': colors,
    })
    seen_sockets.add(socket_ptr)


def collect_node_socket_overlays(node, v2d, zoom, width, target_list, seen_sockets, colors=None, overlay_size=1.0):
    for is_output, sockets in ((False, getattr(node, 'inputs', [])), (True, getattr(node, 'outputs', []))):
        for idx, socket in enumerate(sockets):
            if not getattr(socket, 'enabled', True):
                continue
            try:
                sx, sy = get_socket_loc(node, is_output, idx)
                center = v2d.view_to_region(sx, sy, clip=False)
            except Exception:
                continue

            append_socket_overlay(
                target_list,
                seen_sockets,
                socket,
                center,
                zoom,
                width,
                colors=colors,
                overlay_size=overlay_size,
            )



def _node_location_absolute(node):
    if hasattr(node, "location_absolute"):
        return Vector((node.location_absolute.x, node.location_absolute.y))

    location = Vector((node.location.x, node.location.y))
    node_p = node.parent
    while node_p:
        location += Vector((node_p.location.x, node_p.location.y))
        node_p = node_p.parent
    return location


def node_bounds(node, ui_scale=None):
    """
    计算节点边界框的 View2D 坐标（优化版本，用于减少锯齿）
    """
    metrics = get_layout_metrics()
    scale = metrics['scale'] if ui_scale is None else ui_scale

    di_x = node.dimensions.x
    di_y = node.dimensions.y
    node_location = _node_location_absolute(node)
    node_x = node_location.x
    node_y = node_location.y

    if node.type == "REROUTE":
        reroute_half_size = metrics['reroute_half_size']
        x_center = node_x * scale
        y_center = node_y * scale
        return (
            x_center - reroute_half_size,
            x_center + reroute_half_size,
            y_center - reroute_half_size,
            y_center + reroute_half_size,
        )

    width = di_x * scale
    height = di_y * scale
    x_min = node_x * scale
    x_max = x_min + width

    if node.hide and node.type not in {"REROUTE", "FRAME"}:
        hidden_offset = metrics['hidden_header_offset']
        y_center = node_y * scale - hidden_offset
        y_min = y_center - height / 2
        y_max = y_center + height / 2
    else:
        y_min = node_y * scale
        y_max = y_min - height

    return x_min, x_max, y_min, y_max


def get_rounded_rect_path(node, v2d, radius=4.0, resolution=12, thickness=0.0, socket_masks=None):
    metrics = get_layout_metrics()
    x_min, x_max, y_min, y_max = node_bounds(node, metrics['scale'])

    # 转换到 Region 像素坐标
    p_bl = v2d.view_to_region(x_min, y_min, clip=False)
    p_tr = v2d.view_to_region(x_max, y_max, clip=False)

    if not p_bl or not p_tr:
        return []

    rmin_x = min(p_bl[0], p_tr[0])
    rmax_x = max(p_bl[0], p_tr[0])
    rmin_y = min(p_bl[1], p_tr[1])
    rmax_y = max(p_bl[1], p_tr[1])

    # 向外扩张 (线宽的一半)
    offset = thickness * 0.5
    rmin_x -= offset
    rmax_x += offset
    rmin_y -= offset
    rmax_y += offset

    w = rmax_x - rmin_x
    h = rmax_y - rmin_y

    eff_radius = min(radius, w/2, h/2)

    path = []

    def add_arc(cx, cy, start_ang, end_ang):
        for i in range(resolution + 1):
            t = i / resolution
            ang = start_ang + (end_ang - start_ang) * t
            path.append((cx + eff_radius * cos(ang), cy + eff_radius * sin(ang)))

    path.append(((rmin_x + rmax_x)/2.0, rmin_y))
    add_arc(rmax_x - eff_radius, rmin_y + eff_radius, 1.5 * pi, 2.0 * pi)
    add_arc(rmax_x - eff_radius, rmax_y - eff_radius, 0.0, 0.5 * pi)
    add_arc(rmin_x + eff_radius, rmax_y - eff_radius, 0.5 * pi, 1.0 * pi)
    add_arc(rmin_x + eff_radius, rmin_y + eff_radius, 1.0 * pi, 1.5 * pi)
    path.append(((rmin_x + rmax_x)/2.0, rmin_y))

    return filter_border_path_near_sockets(path, socket_masks)

    
draw_handler = None
last_time = 0
_redraw_timer_interval = 0.1
_SHADER_CACHE = {}

# 用于存储固定的流状态
_locked_flow_data = {
    'links': set(),
    'nodes': set(),
    'is_locked': False
}

def get_shader(name):
    if name in _SHADER_CACHE:
        return _SHADER_CACHE[name]
    
    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant('MAT4', 'ModelViewProjectionMatrix')
    
    # --- 公共 Vertex Source ---
    vert_src = '''
        void main() {
            gl_Position = ModelViewProjectionMatrix * vec4(pos, 0.0, 1.0);
            v_uv = uv;
        }
    '''

    if name == 'RAINBOW':
        iface = gpu.types.GPUStageInterfaceInfo("node_wrangler_rainbow_iface")
        iface.smooth('VEC2', 'v_uv')
        info.vertex_in(0, 'VEC2', 'pos')
        info.vertex_in(1, 'VEC2', 'uv')
        info.vertex_out(iface)
        info.push_constant('FLOAT', 'u_time')
        info.push_constant('FLOAT', 'u_alpha')
        info.fragment_out(0, 'VEC4', 'fragColor')
        info.vertex_source(vert_src)
        
        info.fragment_source('''
            vec3 hsv2rgb(vec3 c) {
                vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
                vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
                return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
            }
            void main() {
                float v_progress = v_uv.x;
                float v_side = v_uv.y;
                float t = u_time * 0.5;
                float flow_phase = t * 3.0 - v_progress * 6.2831853; 
                float hue = fract(flow_phase / 6.2831853);
                
                float saturation = 0.9;
                float value = 0.95;
                float pulse_t = u_time * 1.0;
                float pulse_center = fract(pulse_t);
                float raw_dist = fract(pulse_center - v_progress);
                float pulse = 0.0;
                if (raw_dist > 0.5) {
                     float front_dist = 1.0 - raw_dist;
                     pulse = exp(-(front_dist * front_dist) / 0.0002);
                } else {
                     pulse = exp(-(raw_dist * raw_dist) / 0.08);
                }
                float boost = 1.0 + 0.6 * pulse;
                float sat_damp = 1.0 - 0.2 * pulse;
                
                vec3 rgb = hsv2rgb(vec3(hue, saturation * sat_damp, min(1.0, value * boost)));
                float dist = abs(v_side);
                float alpha_edge = 1.0 - smoothstep(0.85, 1.0, dist);
                fragColor = vec4(rgb, u_alpha * alpha_edge);
            }
        ''')

    # --- 动态颜色渐变 Shader (支持最多10个颜色) ---
    elif name == 'GRADIENT':
        iface = gpu.types.GPUStageInterfaceInfo("node_wrangler_gradient_iface")
        iface.smooth('VEC2', 'v_uv')
        info.vertex_in(0, 'VEC2', 'pos')
        info.vertex_in(1, 'VEC2', 'uv')
        info.vertex_out(iface)
        info.push_constant('FLOAT', 'u_time')
        info.push_constant('FLOAT', 'u_alpha')
        info.push_constant('INT', 'u_color_count')  # 实际使用的颜色数量
        
        # 接收最多10个颜色
        for i in range(10):
            info.push_constant('VEC4', f'color{i+1}')
        
        info.fragment_out(0, 'VEC4', 'fragColor')
        info.vertex_source(vert_src)
        
        info.fragment_source('''
            void main() {
                float v_progress = v_uv.x;
                float v_side = v_uv.y;
                float t = u_time * 0.5;
                
                // 构建颜色数组（包含RGB和Alpha）
                vec3 colors[10];
                float alphas[10];
                colors[0] = color1.rgb; alphas[0] = color1.a;
                colors[1] = color2.rgb; alphas[1] = color2.a;
                colors[2] = color3.rgb; alphas[2] = color3.a;
                colors[3] = color4.rgb; alphas[3] = color4.a;
                colors[4] = color5.rgb; alphas[4] = color5.a;
                colors[5] = color6.rgb; alphas[5] = color6.a;
                colors[6] = color7.rgb; alphas[6] = color7.a;
                colors[7] = color8.rgb; alphas[7] = color8.a;
                colors[8] = color9.rgb; alphas[8] = color9.a;
                colors[9] = color10.rgb; alphas[9] = color10.a;
                
                // 计算流动相位
                float flow_speed = 0.5;
                float phase = (t * flow_speed) - v_progress;
                phase = fract(phase);
                
                // 动态颜色混合
                float n = float(u_color_count);
                float pos = phase * n;
                int index = int(floor(pos));
                float f = fract(pos);
                
                // 确保索引在有效范围内
                index = min(index, u_color_count - 1);
                int next_index = (index + 1) % u_color_count;
                
                // 混合RGB
                vec3 final_base_rgb = mix(colors[index], colors[next_index], f);
                
                // 混合Alpha（每个颜色的独立透明度）
                float final_base_alpha = mix(alphas[index], alphas[next_index], f);
                
                // 脉冲效果
                float pulse_t = u_time * 1.0;
                float pulse_center = fract(pulse_t);
                float raw_dist = fract(pulse_center - v_progress);
                float pulse = 0.0;
                if (raw_dist > 0.5) {
                     float front_dist = 1.0 - raw_dist;
                     pulse = exp(-(front_dist * front_dist) / 0.0002);
                } else {
                     pulse = exp(-(raw_dist * raw_dist) / 0.08);
                }
                float boost = 1.0 + 0.3 * pulse;
                
                vec3 final_rgb = min(vec3(1.0), final_base_rgb * boost);
                
                // 边缘alpha衰减
                float dist = abs(v_side);
                float alpha_edge = 1.0 - smoothstep(0.85, 1.0, dist);
                
                // 最终alpha = 颜色自身alpha * 全局透明度 * 边缘衰减
                float final_alpha = final_base_alpha * u_alpha * alpha_edge;
                fragColor = vec4(final_rgb, final_alpha);
            }
        ''')

    elif name == 'SMOOTH_COLOR':
        iface = gpu.types.GPUStageInterfaceInfo("node_wrangler_smooth_color_iface")
        iface.smooth('VEC2', 'v_uv')
        info.vertex_in(0, 'VEC2', 'pos')
        info.vertex_in(1, 'VEC2', 'uv')
        info.vertex_out(iface)
        info.push_constant('VEC4', 'color')
        info.fragment_out(0, 'VEC4', 'fragColor')
        info.vertex_source(vert_src)
        info.fragment_source('''
            void main() {
                float dist = abs(v_uv.y);
                float alpha_edge = 1.0 - smoothstep(0.85, 1.0, dist);
                fragColor = vec4(color.rgb, color.a * alpha_edge);
            }
        ''')
    


    shader = gpu.shader.create_from_info(info)
    _SHADER_CACHE[name] = shader
    return shader


def _view2d_zoom_factor(v2d):
    try:
        x0, y0 = v2d.region_to_view(0.0, 0.0)
        x1, y1 = v2d.region_to_view(1.0, 0.0)
        dx = abs(x1 - x0)
        if dx <= 1e-8:
            return 1.0
        return 1.0 / dx
    except Exception:
        return 1.0

def get_curving_factor():
    try:
        curving = bpy.context.preferences.themes[0].node_editor.noodle_curving
        return curving / 10.0
    except Exception:
        return 0.0

def _rainbow_rgba(step_t, time_sec):
    t = time_sec * 0.5
    pulse_t = time_sec * 1.0
    pulse_center = pulse_t % 1.0
    flow_phase = t * 3.0 - step_t * 4.0
    hue = (flow_phase / (2 * pi)) % 1.0
    saturation = 0.65
    value = 0.95
    raw_dist = (pulse_center - step_t) % 1.0
    if raw_dist > 0.5:
        front_dist = 1.0 - raw_dist
        pulse = exp(-(front_dist * front_dist) / (2.0 * 0.01 * 0.01))
    else:
        pulse = exp(-(raw_dist * raw_dist) / (2.0 * 0.2 * 0.2))
    boost = 1.0 + 3.0 * pulse
    sat_damp = 1.0 - 0.95 * pulse
    r, g, b = colorsys.hsv_to_rgb(hue, saturation * sat_damp, min(1.0, value * boost))
    return (r, g, b, 1.0)

def get_native_link_points(link, v2d, curv, zoom_factor=1.0, socket_index_cache=None):
    """获取连线点列表，根据缩放级别优化采样点数"""
    fs, ts = link.from_socket, link.to_socket
    cache = socket_index_cache if socket_index_cache is not None else {}
    try:
        if not (fs.enabled and ts.enabled):
            return None
        from_node = link.from_node
        to_node = link.to_node
        from_idx = _get_socket_index_cached(cache, from_node, fs, True) or 0
        to_idx = _get_socket_index_cached(cache, to_node, ts, False) or 0
        x1, y1 = get_socket_loc(from_node, True, from_idx)
        x2, y2 = get_socket_loc(to_node, False, to_idx)
    except Exception:
        return None

    y_off = 0
    y1 += y_off
    y2 += y_off

    v2r = v2d.view_to_region

    # 性能优化：根据缩放级别动态调整采样点数
    # 缩放级别越低（视图越远），使用越少的采样点
    if zoom_factor > 0.5:
        seg = 24  # 高缩放级别：详细采样
    elif zoom_factor > 0.2:
        seg = 16  # 中等缩放级别
    elif zoom_factor > 0.1:
        seg = 12  # 低缩放级别
    else:
        seg = 8   # 极低缩放级别：最少采样

    if curv <= 0.001:
        p0 = (x1, y1)
        p3 = (x2, y2)
        p1 = (x1 + (x2 - x1) * (1.0 / 3.0), y1 + (y2 - y1) * (1.0 / 3.0))
        p2 = (x1 + (x2 - x1) * (2.0 / 3.0), y1 + (y2 - y1) * (2.0 / 3.0))
        pts = []
        for i in range(seg + 1):
            t = i / seg
            x = x1 + t * (x2 - x1)
            y = y1 + t * (y2 - y1)
            pts.append(v2r(x, y, clip=False))
        return pts

    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    if dx != 0:
        slope = dy / dx
    else:
        slope = float('inf')

    curving_factor = curv * 10
    clamp_factor = min(1.0, slope * (4.5 - 0.25 * curving_factor))
    handle_offset = curving_factor * 0.1 * dx * clamp_factor

    p0 = (x1, y1)
    p3 = (x2, y2)
    p1 = (x1 + handle_offset, y1)
    p2 = (x2 - handle_offset, y2)

    pts = []
    for i in range(seg + 1):
        t = i / seg
        inv_t = 1 - t
        inv_t2 = inv_t * inv_t
        inv_t3 = inv_t2 * inv_t
        t2 = t * t
        t3 = t2 * t
        x = (inv_t3 * p0[0] + 3 * inv_t2 * t * p1[0] + 3 * inv_t * t2 * p2[0] + t3 * p3[0])
        y = (inv_t3 * p0[1] + 3 * inv_t2 * t * p1[1] + 3 * inv_t * t2 * p2[1] + t3 * p3[1])
        pts.append(v2r(x, y, clip=False))
    return pts

def _is_link_visible(region, pts, margin=50):
    """检查连线是否在视口中可见（视口裁剪）"""
    if not pts or len(pts) < 2:
        return False
    
    # 如果无法获取区域，假设可见
    if not region:
        return True
    
    view_min_x = 0
    view_min_y = 0
    view_max_x = region.width if hasattr(region, 'width') else 1920  # 默认值
    view_max_y = region.height if hasattr(region, 'height') else 1080  # 默认值
    
    # 检查是否有任何点在视口内（带边距）
    for pt in pts:
        if pt and len(pt) >= 2:
            x, y = pt[0], pt[1]
            if (view_min_x - margin <= x <= view_max_x + margin and 
                view_min_y - margin <= y <= view_max_y + margin):
                return True
    
    return False

def _is_socket_location_plausible(node, x, y, metrics):
    if not (isfinite(x) and isfinite(y)):
        return False

    if node.type == 'REROUTE':
        return True

    x_min, x_max, y_min, y_max = node_bounds(node, metrics['scale'])
    x_margin = max(48.0 * metrics['scale'], metrics['socket_row_height'] * 1.5)
    y_margin = max(96.0 * metrics['scale'], metrics['socket_row_height'] * 2.0)
    return (
        x_min - x_margin <= x <= x_max + x_margin and
        y_max - y_margin <= y <= y_min + y_margin
    )


def get_socket_loc(node, is_output, index):
    sockets = node.outputs if is_output else node.inputs
    metrics = get_layout_metrics()

    try:
        if index < len(sockets):
            socket = sockets[index]
            offset = 520
            if bpy.app.version >= (5, 1, 0):
                offset = 456
            vec = Vector((c_float * 2).from_address(c_void_p.from_address(socket.as_pointer() + offset).value + 24))
            if _is_socket_location_plausible(node, vec.x, vec.y, metrics):
                return vec.x, vec.y
    except Exception:
        pass

    node_location = _node_location_absolute(node)
    base_x = node_location.x * metrics['scale']
    base_y = node_location.y * metrics['scale']

    if node.type == 'REROUTE':
        return base_x, base_y

    x = base_x + node.dimensions.x if is_output else base_x

    enabled_sockets = [s for s in sockets if s.enabled]
    try:
        real_idx = enabled_sockets.index(sockets[index])
    except (ValueError, IndexError):
        real_idx = max(0, min(index, len(enabled_sockets) - 1)) if enabled_sockets else 0

    y = base_y - metrics['socket_header_height']
    y -= (real_idx + 0.5) * metrics['socket_row_height']
    if is_output:
        y += metrics['socket_output_nudge']
    else:
        y -= metrics['socket_output_nudge']
    return x, y

def _get_socket_index_cached(cache, node, socket, is_output):
    key = (node.as_pointer(), bool(is_output))
    socket_map = cache.get(key)
    if socket_map is None:
        sockets = node.outputs if is_output else node.inputs
        socket_map = {s.as_pointer(): i for i, s in enumerate(sockets)}
        cache[key] = socket_map
    return socket_map.get(socket.as_pointer())

def _get_line_strip_geometry(vertices, width):
    if len(vertices) < 2:
        return [], []

    closed_loop = len(vertices) >= 4 and (Vector(vertices[0]) - Vector(vertices[-1])).length <= 1e-4
    verts = [Vector(v) for v in vertices]
    if closed_loop:
        verts = verts[:-1]
        if len(verts) < 3:
            return [], []

    pos_data = []
    uv_data = []
    half_w = width * 0.5
    count = len(verts)

    if closed_loop:
        distances = [0.0]
        total_length = 0.0
        for i in range(count):
            dist = (verts[(i + 1) % count] - verts[i]).length
            total_length += dist
            if i < count - 1:
                distances.append(total_length)

        for i in range(count + 1):
            curr_idx = i % count
            prev_p = verts[(curr_idx - 1) % count]
            curr_p = verts[curr_idx]
            next_p = verts[(curr_idx + 1) % count]

            t1 = (curr_p - prev_p).normalized()
            t2 = (next_p - curr_p).normalized()
            tangent = (t1 + t2).normalized()
            if tangent.length_squared == 0.0:
                tangent = t2 if t2.length_squared > 0.0 else t1
            normal = Vector((-tangent.y, tangent.x))

            p0 = curr_p + normal * half_w
            p1 = curr_p - normal * half_w
            pos_data.append((p0.x, p0.y))
            pos_data.append((p1.x, p1.y))

            u = 1.0 if i == count else (distances[curr_idx] / total_length if total_length > 0.0 else 0.0)
            uv_data.append((u, 1.0))
            uv_data.append((u, -1.0))
        return pos_data, uv_data

    distances = [0.0]
    total_length = 0.0
    for i in range(count - 1):
        dist = (verts[i + 1] - verts[i]).length
        total_length += dist
        distances.append(total_length)

    for i in range(count):
        curr_p = verts[i]
        if i == 0:
            tangent = (verts[1] - curr_p).normalized()
        elif i == count - 1:
            tangent = (curr_p - verts[i - 1]).normalized()
        else:
            t1 = (curr_p - verts[i - 1]).normalized()
            t2 = (verts[i + 1] - curr_p).normalized()
            tangent = (t1 + t2).normalized()
            if tangent.length_squared == 0.0:
                tangent = t2 if t2.length_squared > 0.0 else t1

        normal = Vector((-tangent.y, tangent.x))
        p0 = curr_p + normal * half_w
        p1 = curr_p - normal * half_w

        pos_data.append((p0.x, p0.y))
        pos_data.append((p1.x, p1.y))

        u = distances[i] / total_length if total_length > 0.0 else 0.0
        uv_data.append((u, 1.0))
        uv_data.append((u, -1.0))
    return pos_data, uv_data

def draw_batch_lines(all_lines_data, shader_name, width, colors=None, time_sec=0.0, overall_opacity=1.0):
    if not all_lines_data:
        return

    shader = get_shader(shader_name)
    if not shader:
        return

    all_pos = []
    all_uv = []
    
    for vertices in all_lines_data:
        if not vertices or len(vertices) < 2:
            continue
        pos, uv = _get_line_strip_geometry(vertices, width)
        if not pos:
            continue
        if all_pos:
            all_pos.append(all_pos[-1])
            all_uv.append(all_uv[-1])
            all_pos.append(pos[0])
            all_uv.append(uv[0])
        all_pos.extend(pos)
        all_uv.extend(uv)
        
    if not all_pos:
        return

    shader.bind()
    if shader_name == 'RAINBOW':
        shader.uniform_float("u_time", time_sec % 1000.0)
        shader.uniform_float("u_alpha", overall_opacity)
    elif shader_name == 'GRADIENT':
        shader.uniform_float("u_time", time_sec % 1000.0)
        shader.uniform_float("u_alpha", overall_opacity)
        
        # 获取颜色数量和颜色列表
        color_count = len(colors) if colors else 0
        if color_count < 2:
            # 如果颜色不足，使用默认值
            color_count = 5
            colors = [(0.0, 0.5, 1.0, 1.0), (0.0, 1.0, 0.8, 1.0), (1.0, 1.0, 0.0, 1.0),
                      (1.0, 0.5, 0.0, 1.0), (1.0, 0.0, 0.5, 1.0)]
        
        # 应用全局透明度到每个颜色的alpha值
        # 每个颜色已经有自己的alpha值，现在再乘以全局透明度
        colors = [(c[0], c[1], c[2], (c[3] * overall_opacity) if len(c) > 3 else overall_opacity) for c in colors]
        
        # 设置颜色数量
        shader.uniform_int("u_color_count", color_count)
        
        # 传入最多10个颜色（不足的用最后一个颜色填充）
        color_list = list(colors[:color_count])
        while len(color_list) < 10:
            color_list.append(color_list[-1] if color_list else (1.0, 1.0, 1.0, overall_opacity))
        
        for i in range(10):
            shader.uniform_float(f"color{i+1}", color_list[i])
    elif shader_name == 'SMOOTH_COLOR':
        if colors and len(colors) >= 1:
            # 应用透明度
            color = colors[0]
            if len(color) >= 4:
                color = (color[0], color[1], color[2], color[3] * overall_opacity)
            else:
                color = (*color[:3], overall_opacity)
            shader.uniform_float("color", color)
    
    batch = batch_for_shader(shader, 'TRI_STRIP', {"pos": all_pos, "uv": all_uv})
    batch.draw(shader)


def get_panel_settings():
    try:
        scene = bpy.context.scene
        if hasattr(scene, 'colorful_connections_settings'):
            settings = scene.colorful_connections_settings
            # 辅助函数：转为RGBA（支持从PropertyGroup读取alpha）
            def to_rgba(c):
                alpha = 1.0
                if hasattr(c, 'alpha'):
                    alpha = float(c.alpha)
                
                if isinstance(c, (list, tuple)):
                    if len(c) >= 4:
                        return (float(c[0]), float(c[1]), float(c[2]), float(c[3]))
                    elif len(c) >= 3:
                        return (float(c[0]), float(c[1]), float(c[2]), alpha)
                # 如果是 PropertyGroup 的属性
                if hasattr(c, 'color'):
                    col = c.color
                    return (float(col[0]), float(col[1]), float(col[2]), alpha)
                return (1.0, 1.0, 1.0, alpha)
            
            # 从新的颜色集合中读取（Constant类型）
            gradient_colors = []
            color_count = getattr(settings, 'gradient_color_count', 5)
            colors = getattr(settings, 'gradient_colors', None)
            
            if colors and len(colors) > 0:
                # 只读取实际使用的颜色数量
                for i in range(min(color_count, len(colors))):
                    gradient_colors.append(to_rgba(colors[i]))
            
            # 如果颜色不足，使用默认值
            if len(gradient_colors) < 2:
                gradient_colors = [
                    (0.0, 0.5, 1.0, 1.0),
                    (0.0, 1.0, 0.8, 1.0),
                    (1.0, 1.0, 0.0, 1.0),
                    (1.0, 0.5, 0.0, 1.0),
                    (1.0, 0.0, 0.5, 1.0)
                ]
            
            # 从新的颜色集合中读取（Field类型）
            field_gradient_colors = []
            field_color_count = getattr(settings, 'field_gradient_color_count', 5)
            field_colors = getattr(settings, 'field_gradient_colors', None)
            
            if field_colors and len(field_colors) > 0:
                # 只读取实际使用的颜色数量
                for i in range(min(field_color_count, len(field_colors))):
                    field_gradient_colors.append(to_rgba(field_colors[i]))
            
            # 如果Field颜色不足，使用默认值（紫色系）
            if len(field_gradient_colors) < 2:
                field_gradient_colors = [
                    (0.8, 0.2, 1.0, 1.0),
                    (0.6, 0.4, 1.0, 1.0),
                    (1.0, 0.4, 0.8, 1.0),
                    (0.9, 0.6, 1.0, 1.0),
                    (0.7, 0.3, 0.9, 1.0)
                ]

            endpoint_gradient_colors = []
            endpoint_color_count = getattr(settings, 'endpoint_gradient_color_count', color_count)
            endpoint_colors = getattr(settings, 'endpoint_gradient_colors', None)

            if endpoint_colors and len(endpoint_colors) > 0:
                for i in range(min(endpoint_color_count, len(endpoint_colors))):
                    endpoint_gradient_colors.append(to_rgba(endpoint_colors[i]))

            if len(endpoint_gradient_colors) < 2:
                endpoint_gradient_colors = list(gradient_colors)
            
            # 读取底层背景颜色（新格式：RGB和Alpha分开，兼容旧格式）
            backing_color_rgba = (0.0, 0.0, 0.0, 0.55)  # 默认值
            try:
                # 优先尝试新格式（RGB和Alpha分开）
                # 直接尝试读取，不使用hasattr，因为PropertyGroup的属性应该总是存在
                try:
                    rgb = settings.backing_color_rgb
                    alpha = settings.backing_color_alpha
                    # 处理Blender的Vector类型，转换为tuple
                    if hasattr(rgb, '__len__') and len(rgb) >= 3:
                        backing_color_rgba = (float(rgb[0]), float(rgb[1]), float(rgb[2]), float(alpha))
                    elif isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
                        backing_color_rgba = (float(rgb[0]), float(rgb[1]), float(rgb[2]), float(alpha))
                except AttributeError:
                    # 如果新属性不存在，尝试旧格式（RGBA向量）
                    try:
                        backing_color = settings.backing_color
                        if hasattr(backing_color, '__len__') and len(backing_color) >= 4:
                            backing_color_rgba = (float(backing_color[0]), float(backing_color[1]), float(backing_color[2]), float(backing_color[3]))
                        elif isinstance(backing_color, (list, tuple)) and len(backing_color) >= 4:
                            backing_color_rgba = (float(backing_color[0]), float(backing_color[1]), float(backing_color[2]), float(backing_color[3]))
                    except AttributeError:
                        pass  # 使用默认值
            except Exception as e:
                print(f"读取底层背景颜色时出错: {e}")
                import traceback
                traceback.print_exc()
                backing_color_rgba = (0.0, 0.0, 0.0, 0.55)
            
            return {
                'animation_speed': settings.animation_speed,
                'line_thickness': settings.line_thickness,
                'node_border_thickness': settings.node_border_thickness,
                'endpoint_overlay_size': getattr(settings, 'endpoint_overlay_size', 0.92),
                'endpoint_overlay_thickness': getattr(settings, 'endpoint_overlay_thickness', 0.78),
                'enable_colorful_connections': settings.enable_colorful_connections,
                'connection_color_type': settings.connection_color_type,
                'trace_mode': getattr(settings, 'trace_mode', 'ALL_SELECTED'),
                'flow_direction': getattr(settings, 'flow_direction', 'DOWNSTREAM'),
                'lock_flow': getattr(settings, 'lock_flow', False),
                'enable_type_based_colors': getattr(settings, 'enable_type_based_colors', False),
                'overall_opacity': getattr(settings, 'overall_opacity', 1.0),
                'backing_color': backing_color_rgba,
                'gradient_colors': gradient_colors,
                'field_gradient_colors': field_gradient_colors,
                'endpoint_gradient_colors': endpoint_gradient_colors
            }
        else:
            # 默认值
            return {
                'animation_speed': 1.0,
                'line_thickness': 2.0,
                'node_border_thickness': 3.0,
                'endpoint_overlay_size': 0.92,
                'endpoint_overlay_thickness': 0.78,
                'enable_colorful_connections': True,
                'connection_color_type': 'CUSTOM',
                'trace_mode': 'ALL_SELECTED',
                'flow_direction': 'DOWNSTREAM',
                'lock_flow': False,
                'enable_type_based_colors': False,
                'overall_opacity': 1.0,
                'backing_color': (0.0, 0.0, 0.0, 0.55),  # 默认值，格式：(R, G, B, A)
                'gradient_colors': [
                    (0.0, 0.5, 1.0, 1.0),
                    (0.0, 1.0, 0.8, 1.0),
                    (1.0, 1.0, 0.0, 1.0),
                    (1.0, 0.5, 0.0, 1.0),
                    (1.0, 0.0, 0.5, 1.0)
                ],
                'field_gradient_colors': [
                    (0.8, 0.2, 1.0, 1.0),
                    (0.6, 0.4, 1.0, 1.0),
                    (1.0, 0.4, 0.8, 1.0),
                    (0.9, 0.6, 1.0, 1.0),
                    (0.7, 0.3, 0.9, 1.0)
                ],
                'endpoint_gradient_colors': [
                    (0.0, 0.5, 1.0, 1.0),
                    (0.0, 1.0, 0.8, 1.0),
                    (1.0, 1.0, 0.0, 1.0),
                    (1.0, 0.5, 0.0, 1.0),
                    (1.0, 0.0, 0.5, 1.0)
                ]
            }
    except Exception as e:
        # 调试用
        # print(f"Error in get_panel_settings: {e}")
        return {
            'animation_speed': 1.0,
            'line_thickness': 2.0,
            'node_border_thickness': 3.0,
            'endpoint_overlay_size': 0.92,
            'endpoint_overlay_thickness': 0.78,
            'enable_colorful_connections': True,
            'connection_color_type': 'CUSTOM',
            'trace_mode': 'ALL_SELECTED',
            'flow_direction': 'DOWNSTREAM',
            'lock_flow': False,
            'enable_type_based_colors': False,
            'overall_opacity': 1.0,
            'backing_color': (0.0, 0.0, 0.0, 0.55),
            'gradient_colors': [
                (0.0, 0.5, 1.0, 1.0),
                (0.0, 1.0, 0.8, 1.0),
                (1.0, 1.0, 0.0, 1.0),
                (1.0, 0.5, 0.0, 1.0),
                (1.0, 0.0, 0.5, 1.0)
            ],
            'field_gradient_colors': [
                (0.8, 0.2, 1.0, 1.0),
                (0.6, 0.4, 1.0, 1.0),
                (1.0, 0.4, 0.8, 1.0),
                (0.9, 0.6, 1.0, 1.0),
                (0.7, 0.3, 0.9, 1.0)
            ],
            'endpoint_gradient_colors': [
                (0.0, 0.5, 1.0, 1.0),
                (0.0, 1.0, 0.8, 1.0),
                (1.0, 1.0, 0.0, 1.0),
                (1.0, 0.5, 0.0, 1.0),
                (1.0, 0.0, 0.5, 1.0)
            ]
        }

def extend_links_through_reroutes(links_to_draw, start_node, direction='both', visited_nodes=None):
    if visited_nodes is None:
        visited_nodes = set()
    if start_node in visited_nodes or start_node.type != 'REROUTE':
        return
    visited_nodes.add(start_node)
    
    if direction in ['forward', 'both']:
        for output in start_node.outputs:
            if output.enabled:
                for link in output.links:
                    links_to_draw.add(link)
                    next_node = link.to_node
                    if next_node and next_node.type == 'REROUTE':
                        extend_links_through_reroutes(links_to_draw, next_node, 'forward', visited_nodes)
    
    if direction in ['backward', 'both']:
        for input_socket in start_node.inputs:
            if input_socket.enabled:
                for link in input_socket.links:
                    links_to_draw.add(link)
                    prev_node = link.from_node
                    if prev_node and prev_node.type == 'REROUTE':
                        extend_links_through_reroutes(links_to_draw, prev_node, 'backward', visited_nodes)

def trace_all_reroute_links(selected_node, links_to_draw, visited_nodes=None):
    """旧模式：仅收集选定节点的直接连线 + Reroute 延伸"""
    if visited_nodes is None:
        visited_nodes = set()
    if selected_node in visited_nodes:
        return
    visited_nodes.add(selected_node)
    
    for output in selected_node.outputs:
        if output.enabled:
            for link in output.links:
                links_to_draw.add(link)
                if link.to_node and link.to_node.type == 'REROUTE':
                    extend_links_through_reroutes(links_to_draw, link.to_node, 'forward')
    
    for input_socket in selected_node.inputs:
        if input_socket.enabled:
            for link in input_socket.links:
                links_to_draw.add(link)
                if link.from_node and link.from_node.type == 'REROUTE':
                    extend_links_through_reroutes(links_to_draw, link.from_node, 'backward')

# --- 新的逻辑：真正的深度递归遍历 ---
def traverse_recursive(current_node, direction, collected_links, visited_nodes):
    """
    深度优先搜索，遍历整个节点树的数据流
    
    direction: 'forward' (downstream) or 'backward' (upstream)
    collected_links: 收集到的连线集合
    visited_nodes: 已访问的节点集合（用于防止循环）
    """
    if current_node in visited_nodes:
        return
    visited_nodes.add(current_node)

    if direction == 'forward':
        # 向下查找：Output -> Links -> Next Node
        for output in current_node.outputs:
            if output.enabled:
                for link in output.links:
                    if link not in collected_links:
                        collected_links.add(link)
                        if link.to_node:
                            traverse_recursive(link.to_node, 'forward', collected_links, visited_nodes)
    
    elif direction == 'backward':
        # 向上查找：Input -> Links -> Previous Node
        for input_socket in current_node.inputs:
            if input_socket.enabled:
                for link in input_socket.links:
                    if link not in collected_links:
                        collected_links.add(link)
                        if link.from_node:
                            traverse_recursive(link.from_node, 'backward', collected_links, visited_nodes)

def draw_colorful_connections():
    context = bpy.context
    if context.space_data is None or context.space_data.type != 'NODE_EDITOR':
        return
    tree = context.space_data.node_tree
    if not tree:
        return

    settings = get_panel_settings()
    if not settings.get('enable_colorful_connections', True):
        return

    links_to_draw = set()
    nodes_to_outline = set()  # 用来画边框的节点

    trace_mode = settings.get('trace_mode', 'ALL_SELECTED')

    # --- 逻辑分支 ---
    if trace_mode == 'ALL_SELECTED':
        # 原有逻辑：所有选中节点都发光
        selected_nodes = context.selected_nodes
        if not selected_nodes:
            return
        nodes_to_outline = set(selected_nodes)  # 边框只画选中的
        for node in selected_nodes:
            trace_all_reroute_links(node, links_to_draw)

    elif trace_mode == 'ACTIVE_FLOW':
        # 新逻辑：仅追踪活动节点的数据流
        lock_flow = settings.get('lock_flow', False)

        # 如果取消了锁定，清除保存的状态
        if not lock_flow and _locked_flow_data['is_locked']:
            _locked_flow_data['is_locked'] = False
            _locked_flow_data['links'].clear()
            _locked_flow_data['nodes'].clear()

        # 检查是否需要使用固定的流
        if lock_flow and _locked_flow_data['is_locked']:
            # 使用固定的流数据
            links_to_draw.update(_locked_flow_data['links'])
            nodes_to_outline.update(_locked_flow_data['nodes'])
        else:
            # 重新计算流
            active_node = context.active_node
            if not active_node:
                return

            # 边框始终画活动节点
            nodes_to_outline.add(active_node)

            direction = settings.get('flow_direction', 'DOWNSTREAM')

            if direction == 'BOTH':
                # 双向模式：使用两个独立的 visited_nodes 集合，避免相互干扰
                visited_nodes_forward = set()
                visited_nodes_backward = set()

                # 向下遍历
                traverse_recursive(active_node, 'forward', links_to_draw, visited_nodes_forward)
                # 向上遍历
                traverse_recursive(active_node, 'backward', links_to_draw, visited_nodes_backward)
            else:
                # 单向模式：使用一个集合即可
                visited_nodes_trace = set()
                if direction == 'DOWNSTREAM':
                    traverse_recursive(active_node, 'forward', links_to_draw, visited_nodes_trace)
                elif direction == 'UPSTREAM':
                    traverse_recursive(active_node, 'backward', links_to_draw, visited_nodes_trace)

            # 如果启用了锁定，保存当前的流状态
            if lock_flow:
                _locked_flow_data['links'] = links_to_draw.copy()
                _locked_flow_data['nodes'] = nodes_to_outline.copy()
                _locked_flow_data['is_locked'] = True

    if not links_to_draw and not nodes_to_outline:
        return

    gpu.state.blend_set('ALPHA')

    region = context.region
    v2d = region.view2d
    zoom = _view2d_zoom_factor(v2d)
    border_pixel_size = get_layout_metrics()['pixel_size']

    time_sec = time.time() * settings.get('animation_speed', 1.0)
    connection_color_type = settings.get('connection_color_type', 'CUSTOM')
    overall_opacity = settings.get('overall_opacity', 1.0)
    endpoint_overlay_size = settings.get('endpoint_overlay_size', 0.92)
    endpoint_overlay_thickness = settings.get('endpoint_overlay_thickness', 0.78)

    grad_cols = settings.get('gradient_colors', [])
    field_grad_cols = settings.get('field_gradient_colors', [])
    endpoint_grad_cols = settings.get('endpoint_gradient_colors', [])

    socket_index_cache = {}
    curv_factor = get_curving_factor()
    enable_type_colors = settings.get('enable_type_based_colors', False)
    width_backing = max(2.0, 9.0 * zoom)
    width_main = max(1.5, settings.get('line_thickness', 2.0) * zoom)
    batch_node_bbox = []
    endpoint_overlays = []
    endpoint_overlay_seen = set()



    # 处理节点边框
    bbox_width = max(border_pixel_size, settings.get('node_border_thickness', 3.0) * border_pixel_size * zoom)
    if nodes_to_outline:
        border_thickness = settings.get('node_border_thickness', 3.0)
        bbox_width = max(border_pixel_size, border_thickness * border_pixel_size * zoom)
        pixel_radius = max(3.0, 4.0 * zoom)

        for node in nodes_to_outline:
            node_masks = collect_node_socket_masks(node, v2d, zoom, bbox_width)
            bbox_polys = get_rounded_rect_path(
                node,
                v2d,
                radius=pixel_radius,
                thickness=bbox_width,
                socket_masks=node_masks,
            )
            for bbox_poly in bbox_polys:
                if bbox_poly:
                    batch_node_bbox.append(bbox_poly)

    # 存储每条连线的信息，用于后续绘制
    link_info_list = []
    backing_segments = []
    constant_main_segments = []
    field_main_segments = []
    constant_type_segments = {}
    field_type_segments = {}

    for link in links_to_draw:
        fs = getattr(link, "from_socket", None)
        ts = getattr(link, "to_socket", None)
        if not fs or not ts:
            continue
        n1 = link.from_node
        n2 = link.to_node
        from_idx = _get_socket_index_cached(socket_index_cache, n1, fs, True)
        to_idx = _get_socket_index_cached(socket_index_cache, n2, ts, False)
        if from_idx is None or to_idx is None:
            continue
        # 计算位置
        try:
            # get_socket_loc 可能在特殊情况下失败，加个保护
            l1x, l1y = get_socket_loc(n1, True, from_idx)
            l2x, l2y = get_socket_loc(n2, False, to_idx)
        except:
            continue

        # 性能优化：根据缩放级别调整采样点数
        pts = get_native_link_points(link, v2d, curv_factor, zoom, socket_index_cache=socket_index_cache)
        if not pts or len(pts) < 2:
            continue

        if not _is_link_visible(region, pts, margin=100):
            continue

        from_center = v2d.view_to_region(l1x, l1y, clip=False)
        to_center = v2d.view_to_region(l2x, l2y, clip=False)
        link_socket_masks = []
        _append_socket_mask(link_socket_masks, set(), fs, from_center, zoom, clip_width=width_main, extra_padding=0.2)
        _append_socket_mask(link_socket_masks, set(), ts, to_center, zoom, clip_width=width_main, extra_padding=0.2)
        line_segments = split_polyline_by_socket_masks(pts, link_socket_masks)
        if not line_segments:
            continue

        # 保存连线信息和socket信息
        is_field = is_field_link(tree, link)
        link_colors = field_grad_cols if is_field else grad_cols
        if enable_type_colors:
            link_colors = apply_type_based_color_shift(link_colors, fs, ts, offset_strength=0.5)

        append_socket_overlay(
            endpoint_overlays,
            endpoint_overlay_seen,
            fs,
            from_center,
            zoom,
            max(width_main, bbox_width),
            colors=endpoint_grad_cols,
            overlay_size=endpoint_overlay_size,
        )
        append_socket_overlay(
            endpoint_overlays,
            endpoint_overlay_seen,
            ts,
            to_center,
            zoom,
            max(width_main, bbox_width),
            colors=endpoint_grad_cols,
            overlay_size=endpoint_overlay_size,
        )

        link_info_list.append({
            'pts': line_segments,
            'from_socket': fs,
            'to_socket': ts,
            'is_field': is_field,
            'colors': link_colors,
        })

        backing_segments.extend(line_segments)
        if is_field:
            if enable_type_colors:
                socket_type = get_socket_type_name(ts)
                field_type_segments.setdefault(socket_type, {'segments': [], 'colors': link_colors})
                field_type_segments[socket_type]['segments'].extend(line_segments)
            else:
                field_main_segments.extend(line_segments)
        else:
            if enable_type_colors:
                socket_type = get_socket_type_name(ts)
                constant_type_segments.setdefault(socket_type, {'segments': [], 'colors': link_colors})
                constant_type_segments[socket_type]['segments'].extend(line_segments)
            else:
                constant_main_segments.extend(line_segments)

    for node in nodes_to_outline:
        collect_node_socket_overlays(
            node,
            v2d,
            zoom,
            max(width_main, bbox_width),
            endpoint_overlays,
            endpoint_overlay_seen,
            colors=endpoint_grad_cols,
            overlay_size=endpoint_overlay_size,
        )

    # 1. Backing (底层背景) - 给所有连线画背景
    if backing_segments:
        # 从设置中获取底层背景颜色（draw_batch_lines会自动应用overall_opacity）
        backing_color_setting = settings.get('backing_color', (0.0, 0.0, 0.0, 0.55))
        # 确保是RGBA格式的tuple，并确保所有值都是float
        if isinstance(backing_color_setting, (list, tuple)) and len(backing_color_setting) >= 4:
            backing_color = (
                float(backing_color_setting[0]),
                float(backing_color_setting[1]),
                float(backing_color_setting[2]),
                float(backing_color_setting[3])
            )
        else:
            backing_color = (0.0, 0.0, 0.0, 0.55)

        # 调试：打印颜色值（可以注释掉）
        # print(f"底层背景颜色: {backing_color}, 整体透明度: {overall_opacity}")

        draw_batch_lines(backing_segments, 'SMOOTH_COLOR', width_backing, colors=[backing_color], overall_opacity=overall_opacity)

    # 2. Main Lines - Constant连线：实线流动
    if enable_type_colors:
        for type_group in constant_type_segments.values():
            if not type_group['segments']:
                continue
            draw_batch_lines(
                type_group['segments'],
                'GRADIENT',
                width_main,
                colors=type_group['colors'],
                time_sec=time_sec,
                overall_opacity=overall_opacity,
            )
    elif constant_main_segments:
        draw_batch_lines(constant_main_segments, 'GRADIENT', width_main, colors=grad_cols, time_sec=time_sec, overall_opacity=overall_opacity)

    # 3. Field连线：使用Field配色方案（实线，不再使用虚线）
    if enable_type_colors:
        for type_group in field_type_segments.values():
            if not type_group['segments']:
                continue
            draw_batch_lines(
                type_group['segments'],
                'GRADIENT',
                width_main,
                colors=type_group['colors'],
                time_sec=time_sec,
                overall_opacity=overall_opacity,
            )
    elif field_main_segments:
        draw_batch_lines(field_main_segments, 'GRADIENT', width_main, colors=field_grad_cols, time_sec=time_sec, overall_opacity=overall_opacity)

    # 3. Node Borders
    if batch_node_bbox:
        draw_batch_lines(batch_node_bbox, 'GRADIENT', bbox_width, colors=grad_cols, time_sec=time_sec, overall_opacity=overall_opacity)

    # 4. Endpoint Overlays
    if endpoint_overlays:
        overlays_by_color = {}
        for overlay in endpoint_overlays:
            overlay_colors = overlay['colors'] or endpoint_grad_cols or grad_cols
            colors_key = tuple(tuple(round(v, 6) for v in color) for color in overlay_colors)
            overlays_by_color.setdefault(colors_key, {'paths': [], 'colors': overlay_colors})
            overlays_by_color[colors_key]['paths'].append(overlay['path'])

        for overlay_group in overlays_by_color.values():
            draw_batch_lines(
                overlay_group['paths'],
                'GRADIENT',
                max(width_main, bbox_width) * endpoint_overlay_thickness,
                colors=overlay_group['colors'],
                time_sec=time_sec,
                overall_opacity=overall_opacity,
            )

    gpu.state.blend_set('NONE')
    # 性能优化：根据连线数量动态调整重绘频率
    # 连线数量多时，降低刷新频率以减少GPU负载
    num_links = len(links_to_draw)
    if num_links > 500:
        redraw_interval = 0.2  # 大量连线时，每0.2秒刷新一次
    elif num_links > 200:
        redraw_interval = 0.15  # 中等数量连线
    else:
        redraw_interval = 0.1  # 少量连线，正常刷新频率

    _ensure_redraw_timer(redraw_interval)

def _ensure_redraw_timer(interval):
    global _redraw_timer_interval
    _redraw_timer_interval = max(0.01, float(interval))
    if not bpy.app.timers.is_registered(force_redraw):
        bpy.app.timers.register(force_redraw, first_interval=_redraw_timer_interval)


def force_redraw():
    try:
        for wm in bpy.data.window_managers:
            for window in wm.windows:
                for area in window.screen.areas:
                    if area.type == 'NODE_EDITOR':
                        area.tag_redraw()
    except Exception:
        pass
    return _redraw_timer_interval

def register():
    global draw_handler, _SHADER_CACHE
    # 清除着色器缓存，确保使用最新的着色器代码（包括alpha支持）
    _SHADER_CACHE.clear()
    draw_handler = bpy.types.SpaceNodeEditor.draw_handler_add(
        draw_colorful_connections, (), 'WINDOW', 'POST_PIXEL'
    )

def unregister():
    global draw_handler, _SHADER_CACHE
    if draw_handler:
        bpy.types.SpaceNodeEditor.draw_handler_remove(draw_handler, 'WINDOW')
        draw_handler = None
    # 清除着色器缓存
    _SHADER_CACHE.clear()