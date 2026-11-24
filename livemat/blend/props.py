# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Tom Berczeller

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from .. import icons
from . import composite, data

_channel_items = []  # kept alive: Blender doesn't copy enum item strings


def _channels(_self, _context):
    names = {"R": "Red", "G": "Green", "B": "Blue", "A": "Alpha"}
    _channel_items[:] = [
        (key, key, f"Work on the {names[key].lower()} channel", icons.get(f"channel_{key.lower()}"), number)
        for number, key in enumerate(data.CHANNELS)
    ]
    return _channel_items


def _recomposite(self, _context):
    mesh = self.id_data
    # Only meshes that already have a mask: setting a value elsewhere mustn't create one.
    if isinstance(mesh, bpy.types.Mesh) and data.FINAL in mesh.color_attributes:
        data.composite_mesh(mesh)


def _channel_changed(self, context):
    if self.view_channel:
        self.view_channel = self.channel  # the grayscale view follows the picked channel
    _recomposite(self, context)


LAYER_KINDS = (
    ("FILL", "Fill", "Values written on selections with Set, Randomize or the Polygon Fill tool", "SNAP_FACE", 0),
    ("PAINT", "Paint", "Painted with Blender's vertex paint brushes: white applies the layer's value", "BRUSH_DATA", 1),
    ("GENERATOR", "Generator", "Baked from the shape: ambient occlusion, thickness, curvature or edges", "MOD_SMOOTH", 2),
)

GENERATORS = (
    ("AO", "Ambient Occlusion", "Darker where the surface is hidden from the sky, like in crevices", "SHADING_RENDERED", 0),
    ("THICKNESS", "Thickness", "Darker where the object is thin", "MOD_SOLIDIFY", 1),
    ("CURVATURE", "Curvature", "Bright on bumps and edges, dark in dents, from Cycles' pointiness", "SPHERECURVE", 2),
    ("EDGES", "Edge Wear", "Bright on convex edges, from the angle between faces. No Cycles needed", "MOD_BEVEL", 3),
)


class LiveMatBlendLayer(bpy.types.PropertyGroup):
    # `name` comes from PropertyGroup.
    uid: StringProperty()
    kind: EnumProperty(name="Kind", items=LAYER_KINDS, default="FILL")
    visible: BoolProperty(name="Visible", default=True, update=_recomposite)
    opacity: FloatProperty(name="Opacity", default=1.0, min=0.0, max=1.0, subtype="FACTOR", update=_recomposite)
    blend_mode: EnumProperty(name="Blend", items=composite.BLEND_MODES, default="NORMAL", update=_recomposite)
    # Paint layers
    paint_value: FloatProperty(
        name="Value", default=1.0, min=0.0, max=1.0, subtype="FACTOR",
        description="Value the layer applies where you paint white", update=_recomposite,
    )
    # Generator layers
    generator: EnumProperty(name="Generator", items=GENERATORS, default="AO")
    distance: FloatProperty(
        name="Distance", default=0.5, min=0.001, soft_max=10.0, subtype="DISTANCE",
        description="How far occlusion is looked for (AO and Thickness)",
    )
    samples: IntProperty(name="Samples", default=32, min=1, max=1024, description="Cycles samples for the bake")
    only_local: BoolProperty(name="Only This Object", default=False, description="Ignore other objects when baking AO")
    edge_kind: EnumProperty(
        name="Edges",
        items=[("CONVEX", "Convex", "Ridges"), ("CONCAVE", "Concave", "Valleys"), ("BOTH", "Both", "Ridges and valleys")],
        default="CONVEX",
    )
    low: FloatProperty(
        name="Low", default=0.0, min=0.0, max=1.0, subtype="FACTOR",
        description="Baked values at or below this become 0", update=_recomposite,
    )
    high: FloatProperty(
        name="High", default=1.0, min=0.0, max=1.0, subtype="FACTOR",
        description="Baked values at or above this become 1", update=_recomposite,
    )
    invert: BoolProperty(name="Invert", default=False, update=_recomposite)
    baked: BoolProperty()


class LiveMatSelectionSet(bpy.types.PropertyGroup):
    uid: StringProperty()
    domain: EnumProperty(
        items=[("VERT", "Vertices", "", "VERTEXSEL", 0), ("EDGE", "Edges", "", "EDGESEL", 1), ("FACE", "Faces", "", "FACESEL", 2)]
    )
    count: IntProperty()
    pick: BoolProperty(name="Combine", description="Include this set when combining sets")


def _set_clicked(self, context):
    # Clicking a saved selection selects it again, as asked: no extra button needed.
    if self.id_data.is_editmode and 0 <= self.active_set < len(self.sets):
        from . import selection

        selection.restore(self.id_data, self.sets[self.active_set], extend=False)


class LiveMatBlendMesh(bpy.types.PropertyGroup):
    channel: EnumProperty(name="Channel", items=_channels, default=0, update=_channel_changed)
    painting: StringProperty()  # uid of the Paint layer being painted, empty otherwise
    view_channel: StringProperty()  # the channel shown in grayscale, empty when not isolating
    base: FloatVectorProperty(
        name="Base",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 0.0, 0.0, 0.0),
        description="Value of each channel where no layer covers it",
        update=_recomposite,
    )
    layers_r: CollectionProperty(type=LiveMatBlendLayer)
    layers_g: CollectionProperty(type=LiveMatBlendLayer)
    layers_b: CollectionProperty(type=LiveMatBlendLayer)
    layers_a: CollectionProperty(type=LiveMatBlendLayer)
    active_r: IntProperty()
    active_g: IntProperty()
    active_b: IntProperty()
    active_a: IntProperty()
    sets: CollectionProperty(type=LiveMatSelectionSet)
    active_set: IntProperty(update=_set_clicked)


class LiveMatBlendTool(bpy.types.PropertyGroup):
    """Tool settings, shared by every mesh in the scene."""

    value: FloatProperty(name="Value", default=1.0, min=0.0, max=1.0, subtype="FACTOR", description="Value written by Set")
    random_min: FloatProperty(name="Min", default=0.0, min=0.0, max=1.0)
    random_max: FloatProperty(name="Max", default=1.0, min=0.0, max=1.0)
    random_per: EnumProperty(
        name="Per",
        items=[
            ("VERTEX", "Vertex", "One random value per vertex", "VERTEXSEL", 0),
            ("POLYGON", "Polygon", "One random value per polygon", "FACESEL", 1),
            ("ELEMENT", "Element", "One random value per connected piece", "MESH_CUBE", 2),
            ("EDGE", "Edge", "One random value per selected edge, averaged where edges meet (Edge select mode)", "EDGESEL", 3),
        ],
        default="VERTEX",
    )
    use_seed: BoolProperty(name="Fixed Seed", description="Give the same random values every time")
    seed: IntProperty(name="Seed", default=12345, min=0)
    smooth: BoolProperty(
        name="Smooth Polygons",
        default=True,
        description=(
            "On: polygon selections color their whole vertices, so values fade into neighbors, and per "
            "Polygon values are averaged at shared vertices. Off: hard border and flat value per polygon"
        ),
    )
    angle_kind: EnumProperty(
        name="Edges",
        items=[
            ("CONVEX", "Convex", "Ridges: edges that stick out, like the outside of a box"),
            ("CONCAVE", "Concave", "Valleys: inside corners, like where a wall meets the floor"),
            ("BOTH", "Both", "Convex and concave edges"),
        ],
        default="CONVEX",
    )
    angle_min: FloatProperty(name="Min", default=0.523599, min=0.0, max=3.141593, subtype="ANGLE", description="Smallest bend angle (0 = flat)")
    angle_max: FloatProperty(name="Max", default=3.141593, min=0.0, max=3.141593, subtype="ANGLE", description="Largest bend angle")
    angle_open: BoolProperty(name="Open Edges", description="Also select border edges, which have one face and no angle")
    fill_mode: EnumProperty(
        name="Fill By",
        items=[
            ("POLYGON", "Polygon", "Fill the polygons you click or drag over", "FACESEL", 0),
            ("MESH", "Mesh", "Fill every polygon connected to them", "MESH_CUBE", 1),
            ("UV_ISLAND", "UV Island", "Fill their whole UV islands", "UV", 2),
        ],
        default="POLYGON",
    )
    hit_test: EnumProperty(
        name="Hit Test",
        items=[
            ("INTERSECT", "Intersect", "A rectangle fills polygons it touches"),
            ("CENTER", "Center", "A rectangle fills polygons whose center is inside it"),
        ],
        default="INTERSECT",
    )
    visible_only: BoolProperty(name="Visible Only", default=True, description="A rectangle skips polygons hidden behind others")
    combine: EnumProperty(
        name="Combine",
        items=[
            ("UNION", "Union", "Everything in any picked set"),
            ("INTERSECT", "Intersect", "Only what every picked set shares"),
            ("DIFFERENCE", "Subtract", "The first picked set minus the others"),
        ],
        default="UNION",
    )


_classes = (LiveMatBlendLayer, LiveMatSelectionSet, LiveMatBlendMesh, LiveMatBlendTool)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Mesh.livemat_blend = PointerProperty(type=LiveMatBlendMesh)
    bpy.types.Scene.livemat_blend_tool = PointerProperty(type=LiveMatBlendTool)


def unregister():
    del bpy.types.Scene.livemat_blend_tool
    del bpy.types.Mesh.livemat_blend
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
