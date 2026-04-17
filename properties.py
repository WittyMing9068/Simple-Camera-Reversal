import bpy

from . import utils


class CMP_Line(bpy.types.PropertyGroup):
    start: bpy.props.FloatVectorProperty(size=2, description="Start Point (Normalized)")
    end: bpy.props.FloatVectorProperty(size=2, description="End Point (Normalized)")
    axis: bpy.props.StringProperty(default='X', description="Axis (X, Y, Z)")


class CMP_SceneProperties(bpy.types.PropertyGroup):
    lines: bpy.props.CollectionProperty(type=CMP_Line)
    active_index: bpy.props.IntProperty(default=-1)
    lines_camera: bpy.props.PointerProperty(type=bpy.types.Object, description="Camera bound to current guide lines")

    is_drawing_mode: bpy.props.BoolProperty(default=False)
    is_creating_line: bpy.props.BoolProperty(default=False)

    # 内部变量，用于计算 Delta
    last_world_rotation: bpy.props.FloatProperty(default=0.0)
    last_flip_z: bpy.props.BoolProperty(default=False)

    def update_rotation(self, context):
        import math
        import mathutils

        cam = context.scene.camera
        if not cam:
            return

        pivot = context.scene.cursor.location.copy()
        view_state = utils.capture_camera_view_state(context)

        delta_rot = self.world_rotation - self.last_world_rotation
        self.last_world_rotation = self.world_rotation

        if abs(delta_rot) > 1e-6:
            rot_mat = mathutils.Matrix.Rotation(delta_rot, 4, 'Z')
            cam.matrix_world = utils.rotate_matrix_around_point(cam.matrix_world, rot_mat, pivot)

        if self.flip_z_axis != self.last_flip_z:
            self.last_flip_z = self.flip_z_axis
            flip_mat = mathutils.Matrix.Rotation(math.pi, 4, 'X')
            cam.matrix_world = utils.rotate_matrix_around_point(cam.matrix_world, flip_mat, pivot)

        context.view_layer.update()
        utils.restore_camera_view_state(view_state)

    world_rotation: bpy.props.FloatProperty(
        name="3D Cursor Rotation",
        description="Rotate camera around 3D cursor",
        default=0.0,
        min=-3.1415926,
        max=3.1415926,
        subtype='ANGLE',
        unit='ROTATION',
        update=update_rotation
    )

    flip_z_axis: bpy.props.BoolProperty(
        name="Flip Z Axis",
        description="Flip world Z axis direction around 3D cursor (rotate 180 degrees around X axis)",
        default=False,
        update=update_rotation
    )


def register():
    utils.register_class_safe(CMP_Line)
    utils.register_class_safe(CMP_SceneProperties)
    bpy.types.Scene.cmp_data = bpy.props.PointerProperty(type=CMP_SceneProperties)


def unregister():
    if hasattr(bpy.types.Scene, "cmp_data"):
        del bpy.types.Scene.cmp_data

    utils.unregister_class_safe(CMP_SceneProperties)
    utils.unregister_class_safe(CMP_Line)
